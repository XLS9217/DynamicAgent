import asyncio
import unittest
from dynamic_agent_client import AgentOperator, agent_tool


class AsyncToolsTest(unittest.IsolatedAsyncioTestCase):
    def test_sync_tool_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "async def"):
            class InvalidOperator(AgentOperator):
                @agent_tool()
                def blocking(self):
                    return "unsupported"

    async def test_async_tool_limits_and_cancellation(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class Operator(AgentOperator):
            @agent_tool(count_limit=1)
            async def wait(self):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        operator = Operator()
        task = asyncio.create_task(operator.execute("wait", {}))
        await started.wait()
        self.assertIn("limit reached", await operator.execute("wait", {}))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
        operator.reset_tool_counters()
        self.assertEqual(operator._tool_call_counts["wait"], 0)
