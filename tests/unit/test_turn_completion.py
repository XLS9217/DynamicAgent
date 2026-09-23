"""Script name: test_turn_completion.py. Verify successful completion ordering without live services."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.agent.agent_runner import AgentRunner
from dynamic_agent_service.agent.agent_structs import AgentInvokeResult, AgentState
from dynamic_agent_service.service.service_router import TriggerRequest, trigger
from dynamic_agent_service.service.session_management import RealtimeSession, RealtimeSessionManager


class TurnCompletionTest(unittest.IsolatedAsyncioTestCase):
    """Exercise immediate follow-ups and successful completion with controlled scheduling."""

    async def test_next_http_trigger_is_accepted_before_previous_task_returns(self):
        """A finished frame must permit a new turn without old-task cleanup clobbering it."""
        session = RealtimeSession("test", session_id="completion-test")
        session.agi = AgentGeneralInterface(openai_adapter=object())
        session.load_model_messages = AsyncMock(return_value=[])
        session.append_message = AsyncMock(return_value="trigger-id")
        second_started = asyncio.Event()
        release_second = asyncio.Event()
        tasks = []
        invocation_count = 0
        finished_count = 0

        async def invoke(**kwargs):
            """Hold the second call open while the first task exits."""
            nonlocal invocation_count
            invocation_count += 1
            if invocation_count == 2:
                second_started.set()
                await release_second.wait()
            return AgentInvokeResult(full_text=f"answer-{invocation_count}", tool_calls=[])

        async def send_json(chunk):
            """Start the follow-up at the instant completion becomes visible."""
            nonlocal finished_count
            if not chunk.get("finished"):
                return
            finished_count += 1
            self.assertIs(session.state, AgentState.IDLE)
            self.assertIsNone(session.active_trigger_task)
            if finished_count == 1:
                self.assertEqual(session.append_message.await_args.args, ("assistant", "answer-1"))
                result = await trigger(TriggerRequest(session_id=session.session_id, text="second"))
                self.assertEqual(result["status"], "accepted")
                tasks.append(session.active_trigger_task)
                await asyncio.wait_for(second_started.wait(), 1)

        session.agi._runner._response_handler.invoke = AsyncMock(side_effect=invoke)
        await session.attach_websocket(SimpleNamespace(send_json=send_json))
        with patch.object(RealtimeSessionManager, "_sessions", {session.session_id: session}):
            try:
                await trigger(TriggerRequest(session_id=session.session_id, text="first"))
                first_task = session.active_trigger_task
                await asyncio.wait_for(first_task, 1)
                self.assertIs(session.active_trigger_task, tasks[0])
                self.assertIs(session.state, AgentState.RUNNING)
                release_second.set()
                await asyncio.wait_for(tasks[0], 1)
                self.assertEqual(finished_count, 2)
                self.assertIs(session.state, AgentState.IDLE)
            finally:
                release_second.set()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def test_subagent_is_idle_and_keeps_final_text_at_completion(self):
        """Subagent completion carries its result after runtime state is cleared."""
        parent = AgentRunner("main", "parent", SimpleNamespace(invoke=AsyncMock()))
        runner = AgentRunner("child", "child", SimpleNamespace(invoke=AsyncMock(
            return_value=AgentInvokeResult(full_text="child answer", tool_calls=[]),
        )), parent_runner=parent)

        async def capture(chunk):
            """Verify the parent receives the completed answer with an idle child."""
            self.assertIs(runner.state, AgentState.IDLE)
            self.assertEqual(chunk.text, "child answer")
            self.assertEqual(chunk.parent_runner_id, "parent")

        runner.stream_callback = capture
        await runner.trigger(messages=[])

    async def test_session_stays_busy_until_assistant_history_is_saved(self):
        """Persistence must complete before the finished frame permits another turn."""
        session = RealtimeSession("test", session_id="saving-test")
        session.agi = AgentGeneralInterface(openai_adapter=object())
        session.agi._runner._response_handler.invoke = AsyncMock(
            return_value=AgentInvokeResult(full_text="saved answer", tool_calls=[]),
        )
        session.load_model_messages = AsyncMock(return_value=[])
        saved = False

        async def append(role, content):
            """Check busy state while the asynchronous database write is pending."""
            nonlocal saved
            if role == "assistant":
                self.assertIs(session.state, AgentState.RUNNING)
                await asyncio.sleep(0)
                self.assertIs(session.state, AgentState.RUNNING)
                saved = True
            return "trigger-id"

        async def send_json(chunk):
            """Completion must follow both persistence and state release."""
            if chunk.get("finished"):
                self.assertTrue(saved)
                self.assertIs(session.state, AgentState.IDLE)

        session.append_message = append
        await session.attach_websocket(SimpleNamespace(send_json=send_json))
        task = asyncio.create_task(session.trigger_agent("test"))
        session.active_trigger_task = task
        await task
