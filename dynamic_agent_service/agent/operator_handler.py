
from dynamic_agent_service.agent.agent_structs import AgentToolCall
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.util.debug_cache_writer import debug_cache_json, debug_cache_md

logger = get_my_logger()


class ServiceOperator:
    r"""
    This is the service-side operator for the dynamic_agent_client\src\operator\agent_operator_base.py
    this is for
    1. forwarding the tool call request to client, and let the operator execute and send back
    2. keep track of the result using the tool call id.
    """

    def __init__(self, name: str, description: str | None, flows: list[dict[str, str]] | None, tools: list[dict]):
        self.name = name
        self.description = description
        self.flows = flows
        self.tools = tools  # list of OpenAI function tool schemas
        self.raw_json = None

    @classmethod
    def from_serialized(cls, data: dict) -> "ServiceOperator":
        """
        Construct a ServiceOperator from a serialized operator dict.
        Introduced in dynamic_agent_client/src/operator/agent_operator_base.py
        """
        name = data["name"]
        tools = data.get("tools", [])
        # prefix tool names so the agent can route calls back to the right operator
        for tool in tools:
            func = tool.get("function", {})
            func["name"] = f"{name}_{func['name']}"

        handler = cls(
            name=name,
            description=data.get("description"),
            flows=data.get("flows"),
            tools=tools,
        )
        handler.raw_json = data
        return handler

    def get_menu_item(self):
        """Build a human-readable summary of this operator for the agent's system prompt."""
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

class OperatorHandler:
    """
    Manages the operator dictionary and registration.
    """

    def __init__(self):
        self._operator_dict = {}

    def register_operator(self, operator_data: dict):
        """
        Construct a ServiceOperator from the serialized operator data
        and store it in _operator_dict keyed by name.
        """
        service_operator = ServiceOperator.from_serialized(operator_data)
        self._operator_dict[service_operator.name] = service_operator
        logger.info(f"Registered operator: {service_operator.tools}")

        # DEBUG LINE: comment out or delete
        debug_cache_json(f"operator_{service_operator.name}", service_operator.raw_json)
        debug_cache_json("operator_tools_all", self.get_tools(list(self._operator_dict.keys())))
        debug_cache_md("operator_menu_all", self.get_menu())

    def get_menu(self):
        """Return a combined menu string of all registered operators, separated by -----."""
        menus = [op.get_menu_item() for op in self._operator_dict.values()]
        menu_text = "\n-----\n".join(menus)
        return menu_text

    def get_tools(self, operator_names: list[str]):
        """Collect all OpenAI tool schemas from the given operator names."""
        tools = []
        for name in operator_names:
            op = self._operator_dict.get(name)
            if op:
                tools.extend(op.tools)
        return tools

    def get_operator(self, name: str) -> ServiceOperator:
        return self._operator_dict.get(name)

    async def execute(self, tool_call: AgentToolCall) -> str:
        pass

