import asyncio
import unittest
from unittest.mock import AsyncMock

from dynamic_agent_service.agent.agent_runner import AgentRunner
from dynamic_agent_service.agent.agent_structs import AgentInvokeResult, AgentState, AgentToolCall


class _SessionLoggerStub:
    def trigger_new(self):
        pass

    def trigger_complete(self):
        pass

    def invoke_new(self):
        pass

    def invoke_log(self, record):
        pass

    def log_system(self, event, data=None):
        pass


class AgentRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runner_owns_tool_wait_and_completion_state(self):
        stream_callback = AsyncMock()
        send_tool_calls = AsyncMock()
        runner = AgentRunner(
            openai_adapter=object(),
            send_tool_calls=send_tool_calls,
            stream_callback=stream_callback,
            session_logger=_SessionLoggerStub(),
        )
        runner._response_handler.invoke = AsyncMock(side_effect=[
            AgentInvokeResult(
                full_text="",
                tool_calls=[AgentToolCall(id="call-1", name="Test_tool", arguments="{}")],
            ),
            AgentInvokeResult(full_text="done", tool_calls=[]),
        ])

        await runner.trigger(
            messages=[{"role": "system", "content": "test"}],
            tools=[{"type": "function", "function": {"name": "Test_tool"}}],
        )

        self.assertIs(runner.state, AgentState.GATHERING)
        self.assertIn("call-1", runner.pending_tool_calls)
        send_tool_calls.assert_awaited_once()

        await runner.append_tool_result("call-1", ok=True, result={"value": 1})
        for _ in range(10):
            if runner.state is AgentState.IDLE:
                break
            await asyncio.sleep(0)

        self.assertIs(runner.state, AgentState.IDLE)
        self.assertEqual(runner.pending_tool_calls, {})
        self.assertEqual(runner.pending_tool_results, {})
        self.assertEqual(runner._response_handler.invoke.await_count, 2)
        self.assertTrue(any(call.args[0].finished for call in stream_callback.await_args_list))


if __name__ == "__main__":
    unittest.main()
