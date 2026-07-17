from typing import Callable

from openai import APIError

from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.agent_structs import AgentToolCall, AgentInvokeResult
from dynamic_agent_service.service.service_structs import AgentResponseChunk
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

DATA_INSPECTION_ERROR_MARKER = "DataInspectionFailed"
SAFETY_RETRY_INSTRUCTION = (
    "The previous response may have been rejected by the model provider's safety "
    "inspection. Answer safely and briefly. Avoid explicit, violent, hateful, "
    "sexual, or otherwise sensitive details. If the request cannot be answered "
    "safely, refuse briefly and offer a safe alternative."
)
DATA_INSPECTION_FALLBACK = (
    "I couldn't complete that response because the model provider rejected the "
    "generated output during safety inspection. Please rephrase the request or "
    "remove sensitive details and try again."
)


def _is_data_inspection_failed(exc: Exception) -> bool:
    return isinstance(exc, APIError) and DATA_INSPECTION_ERROR_MARKER in str(exc)


def _with_safety_retry_instruction(messages: list) -> list:
    retry_messages = [dict(message) for message in messages]
    if retry_messages and retry_messages[0].get("role") == "system":
        retry_messages[0]["content"] = (
            f"{retry_messages[0].get('content', '')}\n\n"
            f"Additional safety instruction:\n{SAFETY_RETRY_INSTRUCTION}"
        )
    else:
        retry_messages.insert(0, {"role": "system", "content": SAFETY_RETRY_INSTRUCTION})
    return retry_messages


class AgentResponseHandler:
    """
    The response wrapper for generating response
    """
    def __init__(self, llm_engine: LanguageEngine, parallel_tool_calls: bool = False):
        self.llm_engine = llm_engine
        self.parallel_tool_calls = parallel_tool_calls

    async def _stream_response_flow(
            self,
            messages: list,
            tools: list = None,
            stream_callback: Callable[[str], None] | None = None
    ) -> AgentInvokeResult:
        """
        Handle streaming response flow.

        :param messages: Conversation history in OpenAI format (including system message)
        :param tools: Optional list of tools in OpenAI function calling format
        :param stream_callback: Async callback for content chunks
        :return: AgentInvokeResponse with full text and tool calls
        """
        full_response = ""
        tool_calls_dict = {}
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        async for chunk in self.llm_engine.async_stream_response(messages, tools=tools, parallel_tool_calls=self.parallel_tool_calls):
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
                if stream_callback:
                    await stream_callback(AgentResponseChunk(
                        type="agent_chunk",
                        text="",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    ))

            if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta

                if hasattr(delta, 'content') and delta.content:
                    full_response += delta.content
                    if stream_callback:
                        await stream_callback(AgentResponseChunk(type="agent_chunk", text=delta.content))

                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tool_call_chunk in delta.tool_calls:
                        idx = tool_call_chunk.index
                        if idx not in tool_calls_dict:
                            tool_calls_dict[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": ""
                            }

                        if hasattr(tool_call_chunk, 'id') and tool_call_chunk.id:
                            tool_calls_dict[idx]["id"] = tool_call_chunk.id

                        if hasattr(tool_call_chunk, 'function'):
                            func = tool_call_chunk.function
                            if hasattr(func, 'name') and func.name:
                                tool_calls_dict[idx]["name"] = func.name
                            if hasattr(func, 'arguments') and func.arguments:
                                tool_calls_dict[idx]["arguments"] += func.arguments

        tool_calls = [
            AgentToolCall(
                id=tc["id"],
                name=tc["name"],
                arguments=tc["arguments"]
            )
            for tc in tool_calls_dict.values()
        ]

        if not self.parallel_tool_calls and len(tool_calls) > 1:
            tool_calls = tool_calls[:1]

        return AgentInvokeResult(
            full_text=full_response,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    async def invoke(
            self,
            messages: list,
            tools: list = None,
            stream_callback: Callable[[str], None] | None = None,
    ) -> AgentInvokeResult:
        """
        Invoke the response flow.

        :param messages: Conversation history in OpenAI format (including system message)
        :param tools: Optional list of tools in OpenAI function calling format
        :param stream_callback: Async callback for content chunks
        :return: AgentInvokeResponse with full text and tool calls
        """
        try:
            return await self._stream_response_flow(messages, tools, stream_callback)
        except Exception as exc:
            if not _is_data_inspection_failed(exc):
                raise

            logger.warning("LLM output rejected by provider inspection: %s", exc)

        try:
            return await self._stream_response_flow(
                _with_safety_retry_instruction(messages),
                tools,
                stream_callback,
            )
        except Exception as exc:
            if not _is_data_inspection_failed(exc):
                raise

            logger.warning("LLM safety retry rejected by provider inspection: %s", exc)

            if stream_callback:
                await stream_callback(AgentResponseChunk(type="agent_chunk", text=DATA_INSPECTION_FALLBACK))
            return AgentInvokeResult(full_text=DATA_INSPECTION_FALLBACK, tool_calls=[])
