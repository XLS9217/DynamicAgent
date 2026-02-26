import os
import inspect
from typing import Union, Callable

from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

SYSTEM_MESSAGE_TEMPLATE = """
Your setting is:
{{setting}}

Overall LAW you MUST follow
- gather enough knowledge before you do anything
- reply rule:
    - always reply in user's language
    - keep short informative reply
"""

class AgentGeneralInterface:

    def __init__(self, llm_engine: LanguageEngine = None):
        self.llm_engine = llm_engine
        if self.llm_engine is None:
            self.llm_engine = LanguageEngine(
                api_key=os.getenv("API_KEY"),
                base_url=os.getenv("BASE_URL"),
                model=os.getenv("MODEL_NAME")
            )

        self._system_message_template = SYSTEM_MESSAGE_TEMPLATE
        self._setting = ""
        self._response_handler = AgentResponseHandler(self.llm_engine)

        self._operator_dict = {}

    @classmethod
    async def create(
            cls,
            language_engine: LanguageEngine,
            setting: Union[str, Callable] = "",
    ) -> "AgentGeneralInterface":
        agi = cls(language_engine)
        agi._setting = setting
        return agi

    async def trigger(self, message: dict, stream_callback=None) -> str:
        messages = []
        messages.append({"role": "system", "content": await self._forge_system_message()})
        messages.append({"role": "user", "content": message.get("text", "")})

        invoke_response = await self._response_handler.invoke(
            messages=messages,
            stream_callback=stream_callback,
        )

        # tool call loop will be here

        return invoke_response

    def register_operator(self, operator_serialized_json):
        """
        construct a OperatorHandler save to self._operator_dict
        """
        pass

    async def _forge_system_message(self) -> str:
        if callable(self._setting):
            if inspect.iscoroutinefunction(self._setting):
                setting_str = await self._setting()
            else:
                setting_str = self._setting()
        else:
            setting_str = self._setting

        return self._system_message_template.replace("{{setting}}", setting_str)