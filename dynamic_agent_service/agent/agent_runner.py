import asyncio
import json
from typing import Awaitable, Callable

from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.agent.agent_structs import AgentState, AgentToolCall
from dynamic_agent_service.external_service.openai_adapter import OpenAIAdapter
from dynamic_agent_service.service.service_structs import AgentResponseChunk
from dynamic_agent_service.util.debug_trigger_writer import DebugTriggerWriter
from dynamic_agent_service.util.setup_logging import get_my_logger


logger = get_my_logger("agent")


class AgentRunner:
    """Stateful execution loop for one agent."""

    def __init__(
        self,
        openai_adapter: OpenAIAdapter,
        send_tool_calls: Callable[[list[AgentToolCall]], Awaitable[None]] | None = None,
        stream_callback: Callable | None = None,
        session_logger=None,
    ):
        if openai_adapter is None:
            raise ValueError("A database-resolved OpenAI adapter is required")

        self._response_handler = AgentResponseHandler(openai_adapter)
        self._send_tool_calls = send_tool_calls
        self._stream_callback = stream_callback
        self._session_logger = session_logger

        self.state = AgentState.IDLE
        self.pending_tool_calls: dict[str, AgentToolCall] = {}
        self.pending_tool_results: dict[str, str] = {}
        self._running_message_list: list[dict] = []
        self._tools: list[dict] = []
        self._debug_writer: DebugTriggerWriter | None = None
        self._full_assistant_text = ""

    @property
    def accumulated_assistant_text(self) -> str:
        return self._full_assistant_text

    @property
    def stream_callback(self) -> Callable | None:
        return self._stream_callback

    @stream_callback.setter
    def stream_callback(self, callback: Callable | None) -> None:
        self._stream_callback = callback

    async def trigger(self, messages: list[dict], tools: list[dict] | None = None) -> None:
        if self.state is not AgentState.IDLE:
            raise RuntimeError(f"Agent is {self.state}")

        self.state = AgentState.RUNNING
        self._running_message_list = list(messages)
        self._tools = list(tools or [])
        self._debug_writer = DebugTriggerWriter()
        self._full_assistant_text = ""

        self._debug_writer.put_system(self._running_message_list[0]["content"])
        self._debug_writer.put_tools(self._tools)
        self._session_logger.trigger_new()

        await self.invoke()

    async def invoke(self) -> None:
        if self.state is not AgentState.RUNNING:
            raise RuntimeError(f"Agent is {self.state}")

        self._debug_writer.put_invoke(self._running_message_list)
        self._session_logger.invoke_new()
        self._session_logger.invoke_log({"type": "messages", "messages": self._running_message_list})
        self._session_logger.invoke_log({"type": "tools", "tools": self._tools})

        try:
            invoke_response = await self._response_handler.invoke(
                messages=self._running_message_list,
                tools=self._tools,
                stream_callback=self._stream_callback,
            )
        except Exception as exc:
            self._session_logger.invoke_log({
                "type": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self._session_logger.trigger_complete()
            raise

        self._session_logger.invoke_log({
            "type": "llm_response",
            "full_text": invoke_response.full_text,
            "tool_calls": [tc.model_dump() for tc in invoke_response.tool_calls] if invoke_response.tool_calls else None,
        })

        await self._stream_callback(AgentResponseChunk(type="agent_chunk", text="", invoked=True))

        if invoke_response.full_text:
            self._full_assistant_text += invoke_response.full_text

        if invoke_response.tool_calls:
            logger.info("Tool calls: %s", invoke_response.tool_calls)
            if self._send_tool_calls is None:
                raise RuntimeError("Tool call sender is not configured")

            self._running_message_list.append(self._build_assistant_tool_call_message(invoke_response))
            self._start_tool_result_gather(invoke_response.tool_calls)
            await self._send_tool_calls(invoke_response.tool_calls)
            return

        if invoke_response.full_text:
            self._running_message_list.append({"role": "assistant", "content": invoke_response.full_text})
            self._session_logger.invoke_log({"type": "assistant_final", "content": invoke_response.full_text})
        self._session_logger.trigger_complete()
        await self._stream_callback(AgentResponseChunk(type="agent_chunk", text="", finished=True, invoked=True))
        self._complete_run()

    async def append_tool_result(self, tool_call_id: str, ok: bool, result: object) -> None:
        if self.state is not AgentState.GATHERING:
            self._log_system("tool_result_rejected", {
                "tool_call_id": tool_call_id,
                "reason": f"agent_state:{self.state}",
            })
            raise ValueError(f"Agent is {self.state}")
        if tool_call_id not in self.pending_tool_calls:
            self._log_system("tool_result_rejected", {
                "tool_call_id": tool_call_id,
                "reason": "unknown_tool_call_id",
            })
            raise ValueError("Unknown tool_call_id")
        if tool_call_id in self.pending_tool_results:
            return

        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if not ok and not content.startswith("Error:"):
            content = f"Error: {content}"
        self.pending_tool_results[tool_call_id] = content
        self._log_system("tool_result_received", {
            "tool_call_id": tool_call_id,
            "ok": ok,
        })

        if self._all_tool_results_received():
            asyncio.create_task(self._complete_tool_results_and_invoke())

    def _start_tool_result_gather(self, tool_calls: list[AgentToolCall]) -> None:
        self.state = AgentState.GATHERING
        self.pending_tool_calls = {tool_call.id: tool_call for tool_call in tool_calls}
        self.pending_tool_results = {}
        self._log_system("tool_calls_dispatched", {
            "tool_call_ids": list(self.pending_tool_calls.keys()),
            "tool_names": [tool_call.name for tool_call in tool_calls],
        })

    async def _complete_tool_results_and_invoke(self) -> None:
        if self.state is not AgentState.GATHERING:
            return

        self._log_system("tool_results_complete", {
            "tool_call_ids": list(self.pending_tool_calls.keys()),
        })
        tool_messages = [
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": self.pending_tool_results[tool_call.id],
            }
            for tool_call in self.pending_tool_calls.values()
        ]
        self._running_message_list.extend(tool_messages)
        for message in tool_messages:
            self._session_logger.invoke_log({"type": "tool_execution", **message})

        self._clear_tool_state()
        self.state = AgentState.RUNNING
        await self.invoke()

    def _all_tool_results_received(self) -> bool:
        return all(tool_call_id in self.pending_tool_results for tool_call_id in self.pending_tool_calls)

    def _clear_tool_state(self) -> None:
        self.pending_tool_calls = {}
        self.pending_tool_results = {}

    def _complete_run(self) -> None:
        self._clear_tool_state()
        self._running_message_list = []
        self._tools = []
        self._debug_writer = None
        self._full_assistant_text = ""
        self.state = AgentState.IDLE

    def _log_system(self, event: str, data: dict | None = None) -> None:
        if self._session_logger is not None:
            self._session_logger.log_system(event, data)

    @staticmethod
    def _build_assistant_tool_call_message(invoke_response) -> dict:
        return {
            "role": "assistant",
            "content": invoke_response.full_text or None,
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                }
                for tool_call in invoke_response.tool_calls
            ],
        }
