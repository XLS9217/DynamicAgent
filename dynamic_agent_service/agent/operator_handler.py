
from dynamic_agent_service.agent.agent_structs import AgentToolCall


class OperatorHandler:

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

    @classmethod
    def from_serialized(cls, data: dict) -> "OperatorHandler":
        """Construct an OperatorHandler from a serialized operator dict."""
        return cls(
            name=data["name"],
            description=data.get("description"),
            flows=data.get("flows"),
            tools=data.get("tools", []),
        )

    async def execute(self, client_socket, tool_call: AgentToolCall):
        """
        Forward a tool call to the client via websocket and wait for the result.
        """
        # TODO: implement forwarding to client and collecting result
        pass