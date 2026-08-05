import inspect
import unittest

from dynamic_agent_client import (
    AgentOperator,
    SubagentOperator,
    SubagentRequest,
    agent_tool,
    description,
    flow,
)


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


class SubagentOperatorTest(unittest.IsolatedAsyncioTestCase):
    def test_serializes_exactly_one_delegation_tool(self):
        operator = SubagentOperator(
            lambda request: request,
            candidate_operators=[_CandidateOperator()],
        )

        serialized = operator.get_serialized_operator()

        self.assertEqual(serialized.name, "SubagentOperator")
        self.assertEqual(len(serialized.tools), 1)
        function = serialized.tools[0]["function"]
        self.assertEqual(function["name"], "SubagentOperator_trigger_subagent")
        self.assertEqual(function["parameters"]["required"], ["task", "operator_list"])
        self.assertEqual(function["parameters"]["properties"]["operator_list"]["type"], "array")
        self.assertIn("research and summarize", function["description"])
        self.assertIn('["KnowledgeOperator"]', function["description"])

    def test_rejects_non_callable_trigger(self):
        with self.assertRaises(TypeError):
            SubagentOperator(None)

    def test_assembles_candidate_operators_in_description(self):
        operator = SubagentOperator(
            lambda request: request,
            candidate_operators=[_CandidateOperator()],
        )

        serialized = operator.get_serialized_operator()

        self.assertIn("Candidate operators available to the subagent", serialized.description)
        self.assertIn(
            "- _CandidateOperator: Search the candidate data source.",
            serialized.description,
        )
        self.assertNotIn("1. Search\n2. Summarize", serialized.description)
        self.assertNotIn("_CandidateOperator_search", serialized.description)
        self.assertEqual(len(serialized.tools), 1)

    def test_rejects_invalid_candidate_operator(self):
        with self.assertRaises(TypeError):
            SubagentOperator(lambda request: request, candidate_operators=[object()])

    def test_reports_available_operators_for_unknown_selection(self):
        operator = SubagentOperator(
            lambda request: request,
            candidate_operators=[_CandidateOperator()],
        )

        with self.assertRaisesRegex(
            ValueError,
            r"Unknown candidate operator\(s\): MissingOperator\. Available operators: _CandidateOperator",
        ):
            operator.execute(
                "trigger_subagent",
                {"task": "research", "operator_list": ["MissingOperator"]},
            )

    def test_reports_clear_request_validation_errors(self):
        operator = SubagentOperator(
            lambda request: request,
            candidate_operators=[_CandidateOperator()],
        )

        with self.assertRaisesRegex(ValueError, "task: task must not be empty"):
            operator.execute(
                "trigger_subagent",
                {"task": "   ", "operator_list": ["_CandidateOperator"]},
            )

    async def test_supports_async_trigger(self):
        async def trigger(request: SubagentRequest):
            return f"completed: {request.task} with {request.operator_list[0]}"

        operator = SubagentOperator(trigger, candidate_operators=[_CandidateOperator()])
        result = operator.execute(
            "trigger_subagent",
            {"task": "research", "operator_list": ["_CandidateOperator"]},
        )

        self.assertTrue(inspect.isawaitable(result))
        self.assertEqual(await result, "completed: research with _CandidateOperator")


if __name__ == "__main__":
    unittest.main()
