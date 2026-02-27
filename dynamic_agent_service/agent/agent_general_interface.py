import os
import inspect
from typing import Union, Callable

from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.agent.operator_handler import OperatorHandler

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

        self._operator_handler = OperatorHandler()

    @classmethod
    async def create(
            cls,
            language_engine: LanguageEngine,
            setting: Union[str, Callable] = "",
            tool_execute: Callable = None,
    ) -> "AgentGeneralInterface":
        agi = cls(language_engine)
        agi._setting = setting
        agi._operator_handler.tool_execute = tool_execute
        return agi

    async def trigger(
        self,
        message: dict,
        stream_callback=None
    ) -> str:
        messages = []
        messages.append({"role": "system", "content": await self._forge_system_message()})
        messages.append({"role": "user", "content": message.get("text", "")})

        full_assistant_text = ""

        #TO-DO: Later do a filter logic
        operator_names = list(self._operator_handler._operator_dict.keys())
        tools = self._operator_handler.get_tools(operator_names)

        # initial invoke
        invoke_response = await self._response_handler.invoke(
            messages=messages,
            tools=tools,
            stream_callback=stream_callback,
        )

        if invoke_response.full_text:
            full_assistant_text += invoke_response.full_text

        if not invoke_response.tool_calls:
            # no tool calls, append assistant message and return
            messages.append({"role": "assistant", "content": invoke_response.full_text})
        else:
            # execute tool calls and append messages
            logger.info(f"Tool calls: {invoke_response.tool_calls}")
            execution_messages = await self._operator_handler.execute(invoke_response)
            messages.extend(execution_messages)

            # invoke again with updated messages to get final response
            final_response = await self._response_handler.invoke(
                messages=messages,
                tools=tools,
                stream_callback=stream_callback,
            )

            if final_response.full_text:
                full_assistant_text += final_response.full_text

        return full_assistant_text

    def register_operator(self, operator_data: dict):
        self._operator_handler.register_operator(operator_data)

    async def _forge_system_message(self) -> str:
        if callable(self._setting):
            if inspect.iscoroutinefunction(self._setting):
                setting_str = await self._setting()
            else:
                setting_str = self._setting()
        else:
            setting_str = self._setting

        return self._system_message_template.replace("{{setting}}", setting_str)