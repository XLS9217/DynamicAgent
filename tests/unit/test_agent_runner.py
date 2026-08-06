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

    def invoke_new(self, *args, **kwargs):
        pass

    def invoke_log(self, record, *args, **kwargs):
        pass

    def log_system(self, event, data=None):
        pass


class AgentRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runner_owns_tool_wait_and_completion_state(self):
        stream_callback = AsyncMock()
        send_tool_calls = AsyncMock()
        runner = AgentRunner(
            name="test-agent",
            runner_id="runner-1",
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

    async def test_subagent_emits_metadata_without_streaming_intermediate_text(self):
        stream_callback = AsyncMock()
        parent = AgentRunner(
            name="main",
            runner_id="main-runner",
            openai_adapter=object(),
            stream_callback=AsyncMock(),
            session_logger=_SessionLoggerStub(),
        )
        runner = AgentRunner(
            name="researcher",
            runner_id="child-runner",
            openai_adapter=object(),
            stream_callback=stream_callback,
            session_logger=_SessionLoggerStub(),
            parent_runner=parent,
        )

        async def invoke(messages, tools, stream_callback):
            from dynamic_agent_service.service.service_structs import AgentResponseChunk

            await stream_callback(AgentResponseChunk(type="agent_chunk", text="hidden token"))
            return AgentInvokeResult(full_text="final result", tool_calls=[])

        runner._response_handler.invoke = AsyncMock(side_effect=invoke)
        await runner.trigger(messages=[{"role": "system", "content": "test"}])

        chunks = [call.args[0] for call in stream_callback.await_args_list]
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].invoked)
        self.assertTrue(chunks[1].finished)
        self.assertEqual(chunks[1].text, "final result")
        self.assertEqual(chunks[1].runner_id, "child-runner")
        self.assertEqual(chunks[1].runner_name, "researcher")
        self.assertEqual(chunks[1].parent_runner_id, "main-runner")
        self.assertNotIn("hidden token", [chunk.text for chunk in chunks])


if __name__ == "__main__":
    unittest.main()
