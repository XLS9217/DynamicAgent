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
- never mention what your parameter to the tool is in reply!!!!
- reply rule:
    - always reply in user's language
    - keep short informative reply
- tool use:
    - don't imagine tools up
    - try to use tool to finish the task, but don't use tool when task is completed
    - try to use as less tool calls to finish the task but never avoids necessary tool call
    - One tool at a time, use one tools result to decide next tool use, or you will encounter error !!!!
    - state what you did with the tool
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
        self._tools: list = []
        self._response_handler = AgentResponseHandler(self.llm_engine)
        self.operators: list = []

    @classmethod
    async def create(
            cls,
            language_engine: LanguageEngine,
            setting: Union[str, Callable] = "",
    ) -> "AgentGeneralInterface":
        agi = cls(language_engine)
        agi._setting = setting
        return agi

    def add_operator(self, operator) -> None:
        self.operators.append(operator)
        tools_with_ref = operator.get_tools_with_ref()
        self._tools.extend(tools_with_ref)
        logger.info(f"Registered operator: {type(operator).__name__} with {len(tools_with_ref)} tools")

    async def trigger(self, message: dict, stream_callback=None) -> str:
        system_message = await self._forge_system_message()
        messages = [{"role": "user", "content": message.get("text", "")}]

        full_response, tool_calls_with_results, assistant_msg = await self._response_handler.invoke(
            messages=messages,
            system_prompt=system_message,
            tools_with_ref=self._tools,
            stream_callback=stream_callback,
            is_stream=True
        )

        all_responses = [full_response]

        while tool_calls_with_results:
            if assistant_msg:
                messages.append(assistant_msg)

            for tc in tool_calls_with_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": str(tc["result"])
                })

            full_response, tool_calls_with_results, assistant_msg = await self._response_handler.invoke(
                messages=messages,
                system_prompt=system_message,
                tools_with_ref=self._tools,
                stream_callback=stream_callback,
                is_stream=True
            )
            all_responses.append(full_response)

        return "".join(all_responses)

    async def _forge_system_message(self) -> str:
        if callable(self._setting):
            if inspect.iscoroutinefunction(self._setting):
                setting_str = await self._setting()
            else:
                setting_str = self._setting()
        else:
            setting_str = self._setting

        return self._system_message_template.replace("{{setting}}", setting_str)