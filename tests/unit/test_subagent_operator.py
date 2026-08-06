import unittest
from types import SimpleNamespace

from dynamic_agent_client import AgentOperator, SubagentOperator, agent_tool, description, flow
from dynamic_agent_client.service_handler import ServiceHandler


class _CandidateOperator(AgentOperator):
    @description
    def get_description(self):
        return "Search the candidate data source."

    @flow
    def search_flow(self):
        return "1. Search\n2. Summarize"

    @agent_tool(description="Search candidate records")
    def search(self, query: str):
        return query


class _ResponseStub:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _HttpStub:
    def __init__(self):
        self.calls = []

    async def post(self, url, json, **kwargs):
        self.calls.append({"url": url, "json": json, **kwargs})
        if url.endswith("/init_subagent"):
            return _ResponseStub({"status": "ok", "runner_id": "child-runner", "name": "researcher"})
        if url.endswith("/trigger_subagent"):
            return _ResponseStub({"status": "accepted"})
        return _ResponseStub({"status": "ok"})


class SubagentOperatorTest(unittest.IsolatedAsyncioTestCase):
    def test_serializes_init_and_trigger_tools(self):
        serialized = SubagentOperator([_CandidateOperator()]).get_serialized_operator()

        functions = {tool["function"]["name"]: tool["function"] for tool in serialized.tools}
        self.assertEqual(
            set(functions),
            {"SubagentOperator_init_subagent", "SubagentOperator_trigger_subagent"},
        )
        self.assertEqual(
            functions["SubagentOperator_init_subagent"]["parameters"]["required"],
            ["name", "setting", "operator_list"],
        )
        self.assertEqual(
            functions["SubagentOperator_trigger_subagent"]["parameters"]["required"],
            ["runner_id", "task"],
        )

    def test_description_lists_only_candidate_name_and_description(self):
        serialized = SubagentOperator([_CandidateOperator()]).get_serialized_operator()

        self.assertIn("- _CandidateOperator: Search the candidate data source.", serialized.description)
        self.assertNotIn("1. Search", serialized.description)
        self.assertNotIn("_CandidateOperator_search", serialized.description)

    async def test_rejects_unknown_operator_with_available_names(self):
        operator = SubagentOperator([_CandidateOperator()])
        with self.assertRaisesRegex(
            ValueError,
            r"Unknown candidate operator\(s\): Missing\. Available operators: _CandidateOperator",
        ):
            await operator.execute(
                "init_subagent",
                {"name": "researcher", "setting": "Research.", "operator_list": ["Missing"]},
            )

    async def test_initializes_registers_child_tools_then_fire_and_go_triggers(self):
        previous_http = ServiceHandler._http
        previous_addr = ServiceHandler._server_addr
        previous_clients = ServiceHandler._clients
        http = _HttpStub()
        client = SimpleNamespace(runner_id="main-runner", tool_map={})
        operator = SubagentOperator([_CandidateOperator()])
        ServiceHandler._http = http
        ServiceHandler._server_addr = "http://service"
        ServiceHandler._clients = {"session-1": client}
        try:
            await ServiceHandler.add_operator("session-1", client, operator)
            operator.tool_call_id = "init-call"
            init_result = await client.tool_map["main-runner"]["SubagentOperator_init_subagent"](
                name="researcher",
                setting="Research carefully.",
                operator_list=["_CandidateOperator"],
            )

            self.assertEqual(init_result["runner_id"], "child-runner")
            self.assertIn("_CandidateOperator_search", client.tool_map["child-runner"])
            self.assertEqual(
                client.tool_map["child-runner"]["_CandidateOperator_search"].operator.runner_id,
                "child-runner",
            )

            operator.tool_call_id = "parent-call"
            trigger_result = await client.tool_map["main-runner"]["SubagentOperator_trigger_subagent"](
                runner_id="child-runner",
                task="Investigate the topic.",
            )
            self.assertIsNone(trigger_result)

            init_call = next(call for call in http.calls if call["url"].endswith("/init_subagent"))
            self.assertEqual(init_call["json"]["parent_runner_id"], "main-runner")
            self.assertEqual(init_call["json"]["operators"][0]["name"], "_CandidateOperator")
            trigger_call = next(call for call in http.calls if call["url"].endswith("/trigger_subagent"))
            self.assertEqual(trigger_call["json"]["runner_id"], "child-runner")
            self.assertNotIn("operators", trigger_call["json"])
            self.assertNotIn("setting", trigger_call["json"])
        finally:
            ServiceHandler._http = previous_http
            ServiceHandler._server_addr = previous_addr
            ServiceHandler._clients = previous_clients


if __name__ == "__main__":
    unittest.main()
