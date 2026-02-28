from typing import Callable

from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.agent_structs import AgentToolCall, AgentInvokeResult
from dynamic_agent_service.service.service_structs import AgentResponseChunk
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


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

        async for chunk in self.llm_engine.async_stream_response(messages, tools=tools, parallel_tool_calls=self.parallel_tool_calls):
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

        return AgentInvokeResult(full_text=full_response, tool_calls=tool_calls)

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
        return await self._stream_response_flow(messages, tools, stream_callback)