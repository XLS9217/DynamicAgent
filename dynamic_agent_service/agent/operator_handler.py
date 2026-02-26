"""
This is the service-side operator for the dynamic_agent_client\src\operator\agent_operator_base.py
this is for
1. forwarding the tool call request to client, and let the operator execute and send back
2. keep track of the result using the tool call id.
"""
from dynamic_agent_service.agent.agent_structs import AgentToolCall


class OperatorHandler:

    def __init__(self):
        self.name
        self.descirption
        self.flows
        self.tools
        pass

    def execute(self, client_socket, toolcall:AgentToolCall):
        pass