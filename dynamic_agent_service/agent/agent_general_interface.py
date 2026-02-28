import os
from typing import Callable

from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.agent.operator_handler import OperatorHandler
from dynamic_agent_service.util.debug_trigger_writer import DebugTriggerWriter
from dynamic_agent_service.service.service_structs import AgentResponseChunk

logger = get_my_logger()

SYSTEM_MESSAGE_TEMPLATE = """

Your setting is:
{{setting}}


For tool calling:
1. Use the menu to execute the tool call
2. Always use tool call instead of coming up with your own answer.
Here is the operator menu:
{{operator_menu}}


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
        self._messages = []
        self._compact_limit = 40
        self._compact_target = 20
        self._stream_callback = None
        self._response_handler = AgentResponseHandler(self.llm_engine)

        self._operator_handler = OperatorHandler()

    @classmethod
    async def create(
            cls,
            language_engine: LanguageEngine,
            setting: str = "",
            messages: list = None,
            compact_limit: int = 40,
            compact_target: int = 20,
            tool_execute: Callable = None,
            stream_callback: Callable = None,
    ) -> "AgentGeneralInterface":
        agi = cls(language_engine)
        agi._setting = setting
        agi._messages = messages or []
        agi._compact_limit = compact_limit
        agi._compact_target = compact_target
        agi._stream_callback = stream_callback
        agi._operator_handler.tool_execute = tool_execute
        return agi

    async def trigger(
        self,
        message: dict,
    ) -> str:
        invoke_messages = await self._forge_message_list(message.get("text", ""))

        full_assistant_text = ""

        #TO-DO: Later do a filter logic
        operator_names = list(self._operator_handler._operator_dict.keys())
        tools = self._operator_handler.get_tools(operator_names)

        # DEBUG
        debug_writer = DebugTriggerWriter()
        debug_writer.put_system(invoke_messages[0]["content"])
        debug_writer.put_tools(tools)

        # Loop until no more tool calls are needed
        while True:
            # DEBUG: write new messages before invoke
            debug_writer.put_invoke(invoke_messages)

            # initial or subsequent invoke
            invoke_response = await self._response_handler.invoke(
                messages=invoke_messages,
                tools=tools,
                stream_callback=self._stream_callback,
            )

            # signal invoked after each LLM call
            await self._stream_callback(AgentResponseChunk(type="agent_chunk", text="", invoked=True))

            if invoke_response.full_text:
                full_assistant_text += invoke_response.full_text

            if not invoke_response.tool_calls:
                # no tool calls, append assistant message (if any content) and break
                if invoke_response.full_text:
                    invoke_messages.append({"role": "assistant", "content": invoke_response.full_text})
                break
            else:
                # execute tool calls and append messages
                logger.info(f"Tool calls: {invoke_response.tool_calls}")
                execution_messages = await self._operator_handler.execute(invoke_response)
                invoke_messages.extend(execution_messages)

        # persist user and assistant messages for future triggers
        self._messages.append({"role": "user", "content": message.get("text", "")})
        if full_assistant_text:
            self._messages.append({"role": "assistant", "content": full_assistant_text})

        return full_assistant_text

    def register_operator(self, operator_data: dict):
        self._operator_handler.register_operator(operator_data)

    async def _forge_message_list(self, user_message: str) -> list:
        """
        1. compact messages if over limit
        2. forge system message
        3. append context messages
        4. append user message
        5. return the message list
        """
        if len(self._messages) >= self._compact_limit:
            await self._compact_messages()

        operator_menu = self._operator_handler.get_menu()
        system_content = self._system_message_template.replace("{{setting}}", self._setting).replace("{{operator_menu}}", operator_menu)

        return [
            {"role": "system", "content": system_content},
            *self._messages,
            {"role": "user", "content": user_message}
        ]

    async def _compact_messages(self):
        keep_count = self._compact_target - 1
        old = self._messages[:-keep_count]
        keep = self._messages[-keep_count:]

        await self._stream_callback(AgentResponseChunk(type="agent_chunk", text="", compacting=True))

        summary_response = await self._response_handler.invoke(
            messages=[
                {"role": "system", "content": "Summarize the following conversation concisely. Preserve key facts, decisions, and context."},
                *old,
            ],
            tools=[],
        )

        await self._stream_callback(AgentResponseChunk(type="agent_chunk", text="", compacting=False))

        self._messages = [
            {"role": "assistant", "content": f"Here is the previous conversation:\n{summary_response.full_text}"},
            *keep,
        ]
        logger.info(f"Compacted messages: {len(old)} old -> 1 summary + {len(keep)} kept")