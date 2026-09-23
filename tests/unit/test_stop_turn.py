"""Script name: test_stop_turn.py. Check cancellation and safe session reuse."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from dynamic_agent_client import AgentResponseChunk
from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.agent.agent_structs import AgentState, AgentInvokeResult, AgentToolCall
from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.external_service.openai_adapter import OpenAIAdapter
from dynamic_agent_service.service.session_management import RealtimeSession
from dynamic_agent_service.service.service_router import tool_result
from dynamic_agent_service.service.service_structs import ToolResultRequest


class StopTurnTest(unittest.IsolatedAsyncioTestCase):
    """Exercise streaming, queued continuations, and late tool results."""

    async def asyncSetUp(self):
        """Create a session with isolated persistence and a controlled model."""
        self.session = RealtimeSession(setting="test", session_id="stop-unit")
        self.session.load_model_messages = AsyncMock(return_value=[])
        self.session.append_message = AsyncMock(return_value="message-id")
        self.session.agi = await AgentGeneralInterface.create(openai_adapter=MagicMock())
        self.socket = AsyncMock()
        await self.session.attach_websocket(self.socket)
        self.log_patch = patch("dynamic_agent_service.service.session_management.LogInterface")
        self.logs = self.log_patch.start()
        self.logs.cancel_trigger = AsyncMock()
        self.addCleanup(self.log_patch.stop)

    async def test_stop_stream_persists_partial_before_readiness(self):
        """Stop releases the stream, preserves text, and permits another turn."""
        started = asyncio.Event()
        closed = asyncio.Event()

        async def invoke(**kwargs):
            """Stream one fragment and block until cancelled."""
            await kwargs["stream_callback"](AgentResponseChunk(type="agent_chunk", text="Blue lantern."))
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        self.session.agi._runner._response_handler.invoke = invoke
        self.session.start_trigger("Tell a story", "first")
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(self.session.stop("first"), 1)
        self.assertTrue(closed.is_set())
        self.assertIs(self.session.state, AgentState.IDLE)
        self.session.append_message.assert_any_await("assistant", "Blue lantern.")
        terminal = self.socket.send_json.await_args.args[0]
        self.assertTrue(terminal["cancelled"])
        self.assertEqual(terminal["trigger_id"], "first")
        self.logs.start_trigger.assert_any_call("stop-unit", "first", message_id="message-id")
        self.assertEqual(terminal["text"], "Blue lantern.")
        self.assertTrue((await self.session.stop("first")).cancelled)

        self.session.agi._runner._response_handler.invoke = AsyncMock(return_value=AgentInvokeResult(full_text="pong", tool_calls=[]))
        self.session.start_trigger("Next", "second")
        next_task = self.session.active_trigger_task
        self.assertFalse(await self.session.stop("first"))
        await next_task
        self.assertIs(self.session.state, AgentState.IDLE)

    async def test_stop_cancels_tool_continuation_and_ignores_late_result(self):
        """Track the task started by tool results, including child runner tasks."""
        runner = self.session.agi._runner
        runner._send_tool_calls = AsyncMock()
        runner._response_handler.invoke = AsyncMock(return_value=AgentInvokeResult(
            full_text="", tool_calls=[AgentToolCall(id="tool-1", name="slow", arguments="{}")],
        ))
        self.session.start_trigger("Use a tool", "tool-turn")
        await self.session.active_trigger_task
        self.assertIs(runner.state, AgentState.GATHERING)
        started = asyncio.Event()

        async def continuation(**kwargs):
            """Hold the second model invocation open."""
            started.set()
            await asyncio.Event().wait()

        runner._response_handler.invoke = continuation
        await runner.append_tool_result("tool-1", True, "done")
        await asyncio.wait_for(started.wait(), 1)
        task = runner._continuation_task
        child_task = asyncio.create_task(asyncio.Event().wait())
        self.session.subagent_tasks.add(child_task)
        await self.session.stop("tool-turn")
        self.assertTrue(task.cancelled())
        self.assertTrue(child_task.cancelled())
        self.assertEqual(runner.pending_tool_calls, {})
        with patch("dynamic_agent_service.service.service_router.RealtimeSessionManager.get", return_value=self.session):
            response = await tool_result(ToolResultRequest(
                session_id=self.session.session_id, trigger_id="tool-turn",
                runner_id=runner.runner_id, tool_call_id="tool-1", result="late",
            ))
        self.assertEqual(response["status"], "ignored")

    async def test_stop_before_initial_task_runs_has_no_previous_text(self):
        """An immediate stop must not save the preceding turn's answer again."""
        self.session.agi._runner._full_assistant_text = "previous answer"
        self.session.start_trigger("New task", "new")
        await self.session.stop("new")
        self.session.append_message.assert_not_awaited()
        self.assertIs(self.session.state, AgentState.IDLE)

    async def test_cancelling_chunk_callback_closes_provider_stream(self):
        """Close the HTTP stream even when cancellation occurs outside its iterator."""
        completion = MagicMock()
        completion.__aenter__ = AsyncMock(return_value=completion)
        completion.__aexit__ = AsyncMock(return_value=False)
        completion.__aiter__.return_value = [SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="hello", tool_calls=None))],
            usage=None,
        )]
        adapter = object.__new__(OpenAIAdapter)
        adapter.model = "test"
        adapter.async_client = MagicMock()
        adapter.async_client.chat.completions.create = AsyncMock(return_value=completion)
        handler = AgentResponseHandler(adapter)
        started = asyncio.Event()

        async def callback(chunk):
            """Hold execution after the stream yielded a token."""
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(handler.invoke(messages=[], stream_callback=callback))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        completion.__aexit__.assert_awaited_once()


    async def test_stop_http_returns_result_when_socket_send_fails(self):
        from dynamic_agent_service.service.service_router import StopRequest, stop
        self.session.start_trigger("new", "turn")
        self.socket.send_json.side_effect = RuntimeError("Socket closed")
        with patch("dynamic_agent_service.service.service_router.RealtimeSessionManager.get", return_value=self.session):
            result = await stop(StopRequest(session_id=self.session.session_id, trigger_id="turn"))
            repeated = await stop(StopRequest(session_id=self.session.session_id, trigger_id="turn"))
        self.assertEqual(result, repeated)
        self.assertEqual(result["status"], "stopped")
        self.assertTrue(result["completion"]["cancelled"])
        self.assertIs(self.session.state, AgentState.IDLE)

    async def test_failed_turn_releases_state_and_accepts_followup(self):
        self.session.agi._runner._response_handler.invoke = AsyncMock(side_effect=RuntimeError("model failed"))
        self.session.start_trigger("first", "failed")
        await self.session.active_trigger_task
        self.assertFalse(self.session._trigger_open)
        self.assertIs(self.session.state, AgentState.IDLE)
        self.assertFalse(self.session.accepts_trigger("failed"))
        self.session.agi._runner._response_handler.invoke = AsyncMock(return_value=AgentInvokeResult(full_text="next", tool_calls=[]))
        self.session.start_trigger("next", "next")
        await self.session.active_trigger_task
        self.assertEqual(self.session._terminal_chunk.text, "next")


    async def test_stop_after_natural_completion_returns_saved_result(self):
        self.session.agi._runner._response_handler.invoke = AsyncMock(return_value=AgentInvokeResult(full_text="complete answer", tool_calls=[]))
        self.session.start_trigger("first", "finished")
        await self.session.active_trigger_task
        terminal = await self.session.stop("finished")
        self.assertFalse(terminal.cancelled)
        self.assertEqual(terminal.text, "complete answer")
        self.assertEqual(self.session.append_message.await_count, 2)
        self.assertIsNone(await self.session.stop("unrelated"))

    async def test_failed_final_delivery_preserves_completed_result(self):
        self.session.agi._runner._response_handler.invoke = AsyncMock(return_value=AgentInvokeResult(full_text="saved answer", tool_calls=[]))
        self.socket.send_json.side_effect = RuntimeError("Socket closed")
        self.session.start_trigger("first", "finished")
        await self.session.active_trigger_task
        terminal = await self.session.stop("finished")
        self.assertEqual(terminal.text, "saved answer")
        self.assertFalse(terminal.cancelled)
