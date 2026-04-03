"""
Operator registry and tool execution coordinator.

This module defines the OperatorHandler class, which manages the lifecycle of operators
and coordinates tool execution between the LLM and client webhooks.

Key responsibilities:
1. Register operators sent from clients (stores ServiceOperator instances)
2. Build combined operator menu for system prompt injection
3. Collect tool schemas for LLM function calling
4. Execute tool calls by forwarding to client webhook and collecting results

Architecture:
    LLM returns tool_calls → OperatorHandler.execute() → HTTP POST to client webhook
    → client executes Python method → returns result → formatted as tool_message
    → appended to conversation → next LLM call

The OperatorHandler acts as a bridge between the LLM's tool calling interface and
the client's actual tool implementations, without knowing implementation details.
"""

from dynamic_agent_service.agent.agent_structs import AgentInvokeResult
from dynamic_agent_service.operator.service_operator import ServiceOperator
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.util.debug_cache_writer import debug_cache_json, debug_cache_md

logger = get_my_logger()


class OperatorHandler:
    """
    Registry and coordinator for operators and tool execution.

    Manages a dictionary of registered operators and handles the execution flow
    when the LLM requests tool calls.

    Attributes:
        _operator_dict: Maps operator name to ServiceOperator instance
        tool_execute: Async callback to execute tool via webhook (set by AGI)
    """

    def __init__(self):
        self._operator_dict: dict[str, ServiceOperator] = {}
        self.tool_execute = None  # async callable(AgentToolCall) -> str

    def register_operator(self, operator_data: dict):
        """
        Register a new operator from serialized client data.

        Args:
            operator_data: Serialized operator dict from client
        """
        service_operator = ServiceOperator.from_serialized(operator_data)
        self._operator_dict[service_operator.name] = service_operator
        print(f"Registered operator: {service_operator.name} with {len(service_operator.tools)} tools")

        # debug_cache_json(f"operator_{service_operator.name}", service_operator.raw_json)
        # debug_cache_json("operator_tools_all", self.get_tools(list(self._operator_dict.keys())))
        # debug_cache_md("operator_menu_all", self.get_menu())

    def get_menu(self) -> str:
        """Return combined menu string of all operators, separated by -----."""
        menus = [op.get_menu_item() for op in self._operator_dict.values()]
        return "\n-----\n".join(menus)

    def get_tools(self, operator_names: list[str]) -> list[dict]:
        """Collect all OpenAI tool schemas from the given operator names."""
        tools = []
        for name in operator_names:
            op = self._operator_dict.get(name)
            if op:
                tools.extend(op.tools)
        return tools

    def get_operator(self, name: str) -> ServiceOperator | None:
        return self._operator_dict.get(name)

    async def execute(self, invoke_result: AgentInvokeResult) -> list[dict]:
        """
        Execute tool calls via client webhook and return OpenAI-formatted messages.

        Takes the LLM's invoke result containing tool calls, forwards each to the
        client webhook via self.tool_execute, and returns the assistant + tool messages
        ready to append to the conversation.

        Args:
            invoke_result: LLM response containing tool_calls and optional text

        Returns:
            [assistant_message_with_tool_calls, tool_result_1, tool_result_2, ...]
        """
        assistant_message = {
            "role": "assistant",
            "content": invoke_result.full_text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments
                    }
                }
                for tc in invoke_result.tool_calls
            ]
        }

        tool_messages = []
        for tc in invoke_result.tool_calls:
            result = await self.tool_execute(tc)
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })

        # logger.info(f"Assistant message: {assistant_message}")
        # logger.info(f"Tool messages: {tool_messages}")

        return [assistant_message] + tool_messages