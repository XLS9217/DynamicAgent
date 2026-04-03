"""
Service-side representation of a client operator.

This module defines the ServiceOperator class, which acts as the service-side mirror
of the client's AgentOperator. It stores the operator's metadata (name, description, flows)
and tool schemas in OpenAI function calling format.

Key responsibilities:
1. Deserialize operator data sent from the client
2. Store tool schemas (already prefixed with operator name by client)
3. Generate human-readable menu items for the agent's system prompt

The ServiceOperator does NOT execute tools - it only holds metadata. Tool execution
is delegated back to the client via webhook (handled by OperatorHandler).

Flow:
    Client AgentOperator → serialize() → HTTP POST → ServiceOperator.from_serialized()
    → stored in OperatorHandler registry → menu injected into system prompt
"""

from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class ServiceOperator:
    """
    Service-side representation of a client operator.

    Stores operator metadata and tool schemas received from the client.
    Does not execute tools - only provides metadata for LLM context.

    Attributes:
        name: Operator class name (e.g., "MathOperator")
        description: Human-readable description for system prompt
        flows: List of step-by-step instruction dicts for complex operations
        tools: List of OpenAI function tool schemas (names already prefixed)
        raw_json: Original serialized data for debugging
    """

    def __init__(
        self,
        name: str,
        description: str | None,
        flows: list[dict[str, str]] | None,
        tools: list[dict]
    ):
        self.name = name
        self.description = description
        self.flows = flows
        self.tools = tools
        self.raw_json = None

    @classmethod
    def from_serialized(cls, data: dict) -> "ServiceOperator":
        """
        Construct a ServiceOperator from serialized operator data sent by client.

        Args:
            data: Serialized operator dict with keys: name, description, flows, tools

        Returns:
            ServiceOperator instance with populated fields
        """
        operator = cls(
            name=data["name"],
            description=data.get("description"),
            flows=data.get("flows"),
            tools=data.get("tools", []),
        )
        operator.raw_json = data
        return operator

    def get_menu_item(self) -> str:
        """
        Build human-readable summary for agent's system prompt.

        Formats operator metadata into markdown-style text that gets injected
        into the system prompt, allowing the LLM to understand available tools.

        Returns:
            Formatted string with operator name, description, flows, and tool list
        """
        lines = [
            f"# Operator Name: {self.name}",
            f"## Operator Description:",
            self.description or '',
        ]

        if self.flows:
            lines.append(f"## Flows for tool with prefix {self.name}:")
            for flow_dict in self.flows:
                for flow_name, flow_content in flow_dict.items():
                    lines.append(f"### {flow_name}:")
                    lines.append(flow_content)

        lines.append("## Tools:")
        for tool in self.tools:
            func = tool.get("function", {})
            lines.append(f"- {func.get('name', '')}: {func.get('description', '')}")

        return "\n".join(lines)