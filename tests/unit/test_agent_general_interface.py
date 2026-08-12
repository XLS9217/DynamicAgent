import unittest
from types import SimpleNamespace

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface


class _OpenAIAdapterStub:
    def __init__(self):
        self.calls = []

    async def async_stream_response(self, messages, tools=None, parallel_tool_calls=False):
        self.calls.append({"messages": messages, "tools": tools})
        yield SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content="subagent result", tool_calls=None),
            )],
            usage=None,
        )


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

    def test_assigns_unique_runner_ids_and_rejects_duplicate_names(self):
        interface = AgentGeneralInterface(
            openai_adapter=object(),
        )
        child = interface._create_runner(
            name="researcher",
            openai_adapter=object(),
            stream_callback=None,
            log_session_id=None,
        )

        self.assertEqual(interface._runner.name, "main")
        self.assertNotEqual(interface.runner_id, child.runner_id)
        with self.assertRaisesRegex(ValueError, "Agent runner name already exists: researcher"):
            interface._create_runner(
                name="researcher",
                openai_adapter=object(),
                stream_callback=None,
                log_session_id=None,
            )

    async def test_triggers_named_subagent_with_selected_setting_and_operators(self):
        adapter = _OpenAIAdapterStub()
        interface = AgentGeneralInterface(
            openai_adapter=adapter,
        )
        operators = [{
            "name": "ResearchOperator",
            "description": "Research information.",
            "tools": [],
        }]

        runner_id = interface.init_subagent(
            parent_runner_id=interface.runner_id,
            name="researcher",
            setting="You are a research specialist.",
            operators=operators,
        )
        result = await interface.trigger_subagent(
            runner_id=runner_id,
            parent_tool_call_id="parent-call",
            task="Investigate the topic.",
        )

        self.assertEqual(result, "subagent result")
        self.assertEqual(list(interface._runner_id_by_name), ["main", "researcher"])
        messages = adapter.calls[0]["messages"]
        self.assertIn("You are a research specialist.", messages[0]["content"])
        self.assertIn("ResearchOperator", messages[0]["content"])
        self.assertIn(
            {"role": "user", "content": "Investigate the topic."},
            messages,
        )

    async def test_rejects_duplicate_subagent_operator_names(self):
        interface = AgentGeneralInterface(
            openai_adapter=object(),
        )

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate subagent operator names: DuplicateOperator",
        ):
            interface.init_subagent(
                parent_runner_id=interface.runner_id,
                name="researcher",
                setting="Research carefully.",
                operators=[
                    {"name": "DuplicateOperator", "tools": []},
                    {"name": "DuplicateOperator", "tools": []},
                ],
            )


if __name__ == "__main__":
    unittest.main()
