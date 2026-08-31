import asyncio
import json
from typing import Awaitable, Callable

from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.agent.agent_structs import AgentState, AgentToolCall
from dynamic_agent_client.client_struct import AgentResponseChunk


class AgentRunner:
    """Stateful execution loop for one agent."""

    def __init__(
        self,
        name: str,
        runner_id: str,
        response_handler: AgentResponseHandler,
        send_tool_calls: Callable[[list[AgentToolCall]], Awaitable[None]] | None = None,
        stream_callback: Callable | None = None,
        parent_runner: "AgentRunner | None" = None,
    ):
        if response_handler is None:
            raise ValueError("An agent response handler is required")
        if not name.strip():
            raise ValueError("Agent runner name must not be empty")
        if not runner_id.strip():
            raise ValueError("Agent runner ID must not be empty")

        self.name = name.strip()
        self.runner_id = runner_id.strip()
        self._response_handler = response_handler
        self._send_tool_calls = send_tool_calls
        self._stream_callback = stream_callback
        self.parent_runner = parent_runner
        self.parent_tool_call_id: str | None = None

        self.state = AgentState.IDLE
        self.pending_tool_calls: dict[str, AgentToolCall] = {}
        self.pending_tool_results: dict[str, str] = {}
        self._running_message_list: list[dict] = []
        self._tools: list[dict] = []
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
        self._full_assistant_text = ""

        await self.invoke()

    async def invoke(self) -> None:
        if self.state is not AgentState.RUNNING:
            raise RuntimeError(f"Agent is {self.state}")

        invoke_response = await self._response_handler.invoke(
            messages=self._running_message_list,
            tools=self._tools,
            stream_callback=self._handle_response_chunk,
        )

        if invoke_response.full_text:
            self._full_assistant_text += invoke_response.full_text

        finished = not invoke_response.tool_calls
        await self._emit_chunk(AgentResponseChunk(
            type="agent_chunk",
            text=(
                self._full_assistant_text
                if finished and self.parent_runner is not None
                else ""
            ),
            invoked=True,
            finished=finished,
        ))

        if invoke_response.tool_calls:
            if self._send_tool_calls is None:
                raise RuntimeError("Tool call sender is not configured")

            self._running_message_list.append(self._build_assistant_tool_call_message(invoke_response))
            self._start_tool_result_gather(invoke_response.tool_calls)
            await self._send_tool_calls(invoke_response.tool_calls)
            return

        if invoke_response.full_text:
            self._running_message_list.append({"role": "assistant", "content": invoke_response.full_text})
        self._complete_run()

    async def _handle_response_chunk(self, chunk: AgentResponseChunk) -> None:
        """Forward model stream chunks with runner metadata."""
        await self._emit_chunk(chunk)

    async def _emit_chunk(self, chunk: AgentResponseChunk) -> None:
        if self._stream_callback is None:
            return
        await self._stream_callback(chunk.model_copy(update={
            "runner_id": self.runner_id,
            "runner_name": self.name,
            "parent_runner_id": (
                self.parent_runner.runner_id if self.parent_runner is not None else None
            ),
            "parent_tool_call_id": self.parent_tool_call_id,
        }))

    async def append_tool_result(self, tool_call_id: str, ok: bool, result: object) -> None:
        if self.state is not AgentState.GATHERING:
            raise ValueError(f"Agent is {self.state}")
        if tool_call_id not in self.pending_tool_calls:
            raise ValueError("Unknown tool_call_id")
        if tool_call_id in self.pending_tool_results:
            return

        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if not ok and not content.startswith("Error:"):
            content = f"Error: {content}"
        self.pending_tool_results[tool_call_id] = content

        if self._all_tool_results_received():
            asyncio.create_task(self._complete_tool_results_and_invoke())

    def _start_tool_result_gather(self, tool_calls: list[AgentToolCall]) -> None:
        self.state = AgentState.GATHERING
        self.pending_tool_calls = {tool_call.id: tool_call for tool_call in tool_calls}
        self.pending_tool_results = {}

    async def _complete_tool_results_and_invoke(self) -> None:
        if self.state is not AgentState.GATHERING:
            return

        tool_messages = [
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": self.pending_tool_results[tool_call.id],
            }
            for tool_call in self.pending_tool_calls.values()
        ]
        self._running_message_list.extend(tool_messages)
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
        self._full_assistant_text = ""
        self.state = AgentState.IDLE

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
