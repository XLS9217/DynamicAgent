
from dynamic_agent_service.agent.agent_structs import AgentToolCall
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.util.debug_cache_writer import debug_cache_json

logger = get_my_logger()


class ServiceOperator:
    """
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
        handler = cls(
            name=data["name"],
            description=data.get("description"),
            flows=data.get("flows"),
            tools=data.get("tools", []),
        )
        handler.raw_json = data
        return handler

    def get_menu_item(self):
        """
        Generate a menu which is a string like following:
        Operator Name: [Operator Name]
        Operator Description: [Description of the operator]
        Flows for tool with prefix [Operator Name]:
            - list of name:content
        Tools:
            - list of name:description
            - but the list will have [Operator Name] as prefix, for example [Operator Name]_[actual_tool_name]
            - when recording the tools in from_serialized, make sure the name will be [Operator Name]_[actual_tool_name]
        """
        menu = f""
        return menu

    async def execute(self, client_socket, tool_call: AgentToolCall):
        """
        Forward a tool call to the client via websocket and wait for the result.
        """
        # TODO: implement forwarding to client and collecting result
        pass


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

        debug_cache_json(f"operator_{service_operator.name}", service_operator.raw_json)

    def get_menu(self):
        """
        return the menu of all service operators split by ----
        it will look like
        [menu1]
        -----
        [menu2]
        -----
        [menu3]
        """

    def get_tools(self, operator_name:list[str]):
        """
        get all tools from selected operators
        """

    def get_operator(self, name: str) -> ServiceOperator:
        return self._operator_dict.get(name)