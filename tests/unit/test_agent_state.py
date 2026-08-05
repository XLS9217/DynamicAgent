import unittest
from types import SimpleNamespace

from dynamic_agent_service.agent.agent_structs import AgentState
from dynamic_agent_service.service.session_management import RealtimeSession


class AgentStateTest(unittest.TestCase):
    def test_state_values_remain_wire_compatible(self):
        self.assertEqual(str(AgentState.IDLE), "idle")
        self.assertEqual(str(AgentState.RUNNING), "running")
        self.assertEqual(str(AgentState.GATHERING), "gathering_tool_result")

    def test_session_exposes_agent_state_enum(self):
        session = RealtimeSession("test")
        self.assertIs(session.state, AgentState.IDLE)

        session.agi = SimpleNamespace(state=AgentState.GATHERING)
        self.assertIs(session.state, AgentState.GATHERING)


if __name__ == "__main__":
    unittest.main()
