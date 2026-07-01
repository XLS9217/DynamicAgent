"""
Operator registry and tool execution coordinator.

This module defines the OperatorHandler class, which manages the lifecycle of operators
and provides LLM-facing tool metadata.

Key responsibilities:
1. Register operators sent from clients (stores ServiceOperator instances)
2. Build combined operator menu for system prompt injection
3. Collect tool schemas for LLM function calling
4. Build OpenAI-format assistant tool-call messages

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
    """

    def __init__(self):
        self._operator_dict: dict[str, ServiceOperator] = {}

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

    def build_assistant_tool_call_message(self, invoke_result: AgentInvokeResult) -> dict:
        return {
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
