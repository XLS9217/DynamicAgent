from typing import Callable

from dynamic_agent_service.agent.language_engine import LanguageEngine
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
            stream_callback: Callable[[str], None] | None
    ) -> str:
        """
        Handle streaming response flow.

        :param messages: Conversation history in OpenAI format (including system message)
        :param stream_callback: Async callback for content chunks
        :return: Full response text
        """
        full_response = ""

        for chunk in self.llm_engine.stream_response(messages, parallel_tool_calls=self.parallel_tool_calls):
            if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta

                if hasattr(delta, 'content') and delta.content:
                    full_response += delta.content
                    if stream_callback:
                        await stream_callback(delta.content)

        return full_response

    async def invoke(
            self,
            messages: list,
            stream_callback: Callable[[str], None] | None = None,
    ) -> str:
        """
        Invoke the response flow.

        :param messages: Conversation history in OpenAI format (including system message)
        :param stream_callback: Async callback for content chunks
        :return: Full response text
        """
        return await self._stream_response_flow(messages, stream_callback)