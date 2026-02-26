from openai import OpenAI, AsyncOpenAI

from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class LanguageEngine:

    def __init__(self, api_key: str, base_url: str, model: str = "qwen3-max"):
        """
        Initialize the LLM Engine with API credentials

        Args:
            api_key: API key for the LLM service
            base_url: Base URL for the LLM API
            model: Model name to use (default: qwen3-max)
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model

    def stream_response(
            self,
            messages: list,
            tools: list = None,
            parallel_tool_calls: bool = False
    ):
        """
        Generate a streaming response from the LLM

        :param messages: List of message dicts in OpenAI format (including system message)
        :param tools: Optional list of tools in OpenAI function calling format
        :param parallel_tool_calls: Whether to allow parallel tool calls (default: False)
        :yields: Chunks of the response as they arrive
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "parallel_tool_calls": parallel_tool_calls
        }
        if tools:
            kwargs["tools"] = tools

        completion = self.client.chat.completions.create(**kwargs)

        for chunk in completion:
            yield chunk

    # async def async_response(
    #         self,
    #         messages: list,
    #         system_prompt: str = "You are a helpful assistant.",
    # ) -> str:
    #     """Async version of generate_response"""
    #     full_messages = [{"role": "system", "content": system_prompt}] + messages
    #     completion = await self.async_client.chat.completions.create(
    #         model=self.model,
    #         messages=full_messages,
    #     )
    #     return completion.choices[0].message.content