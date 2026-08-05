import unittest

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface


class AgentGeneralInterfaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_builds_one_system_prompt_with_operator_guidance(self):
        interface = AgentGeneralInterface(openai_adapter=object())
        interface._setting = "You are the main agent."
        interface.register_operator({
            "name": "ExampleOperator",
            "description": "Provides example capabilities.",
            "flows": [{"example_flow": "1. Inspect\n2. Return"}],
            "tools": [],
        })

        messages = await interface._forge_message_list(
            "Do the task",
            history=[{"role": "assistant", "content": "Previous response"}],
        )

        self.assertEqual([message["role"] for message in messages], ["system", "assistant", "user"])
        system_prompt = messages[0]["content"]
        self.assertIn("You are the main agent.", system_prompt)
        self.assertIn("ExampleOperator", system_prompt)
        self.assertIn("Provides example capabilities.", system_prompt)
        self.assertIn("1. Inspect\n2. Return", system_prompt)
        self.assertEqual(messages[-1]["content"], "Do the task")

    def test_system_prompt_states_when_no_operators_are_available(self):
        interface = AgentGeneralInterface(openai_adapter=object())

        self.assertIn("No operators are available.", interface._build_system_prompt())


if __name__ == "__main__":
    unittest.main()
