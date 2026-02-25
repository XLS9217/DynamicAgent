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

    def generate_response(
            self,
            messages: list,
            system_prompt: str = "You are a helpful assistant.",
            tools: list = None
    ) -> str:
        """
        Generate a non-streaming response from the LLM

        :param messages: List of message dicts in OpenAI format [{"role": "user", "content": "..."}]
        :param system_prompt: System prompt to set the assistant's behavior
        :param tools: Optional list of tools in OpenAI function calling format
        :return: Complete response string from the LLM
        """
        # Prepend system message to the messages
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        kwargs = {
            "model": self.model,
            "messages": full_messages,
            "stream": False
        }
        if tools:
            kwargs["tools"] = tools

        completion = self.client.chat.completions.create(**kwargs)
        return completion.choices[0].message

    def stream_response(
            self,
            messages: list,
            system_prompt: str = "You are a helpful assistant.",
            tools: list = None
    ):
        """
        Generate a streaming response from the LLM

        :param messages: List of message dicts in OpenAI format [{"role": "user", "content": "..."}]
        :param system_prompt: System prompt to set the assistant's behavior
        :param tools: Optional list of tools in OpenAI function calling format
        :yields: Chunks of the response as they arrive
        """
        # Prepend system message to the messages
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        kwargs = {
            "model": self.model,
            "messages": full_messages,
            "stream": True,
            "parallel_tool_calls":False
        }
        if tools:
            kwargs["tools"] = tools

        completion = self.client.chat.completions.create(**kwargs)

        for chunk in completion:
            yield chunk

    async def async_response(
            self,
            messages: list,
            system_prompt: str = "You are a helpful assistant.",
    ) -> str:
        """Async version of generate_response"""
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        completion = await self.async_client.chat.completions.create(
            model=self.model,
            messages=full_messages,
        )
        return completion.choices[0].message.content