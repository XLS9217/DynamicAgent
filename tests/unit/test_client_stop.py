"""Script name: test_client_stop.py. Verify SDK stop and stale-turn filtering."""

import asyncio
import unittest
from unittest.mock import patch

from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler


class ClientStopTest(unittest.IsolatedAsyncioTestCase):
    """Drive actual SDK message handling through a controlled WebSocket stream."""

    async def test_stop_resolves_partial_and_filters_previous_turn(self):
        """A delayed old chunk cannot contaminate an immediate follow-up."""
        client = DynamicAgentClient()
        client.session_id = "session"
        client.runner_id = "main"
        queue = asyncio.Queue()
        first_text = asyncio.Event()
        events = []
        chunks = []
        turns = []

        async def messages():
            """Yield serialized service messages until the listener is cancelled."""
            while True:
                yield await queue.get()

        async def send(trigger_id, text, **flags):
            """Enqueue a typed service chunk."""
            import json
            await queue.put(json.dumps(dict(type="agent_chunk", runner_id="main", trigger_id=trigger_id, text=text, **flags)))

        async def trigger(session_id, text, trigger_id=None):
            """Simulate a stopped first turn and successful follow-up."""
            turns.append(trigger_id)
            if len(turns) == 1:
                await send(trigger_id, "hello")
            else:
                await send(turns[0], "OLD OUTPUT")
                await send(turns[0], "old partial", finished=True, cancelled=True)
                await send(trigger_id, "pong")
                await send(trigger_id, "", finished=True, invoked=True)

        async def stop(session_id, trigger_id):
            """Acknowledge cancellation with the persisted partial response."""
            await send(trigger_id, "hello", finished=True, cancelled=True)
            return {"status": "stopped", "completion": dict(type="agent_chunk", runner_id="main", trigger_id=trigger_id, text="hello", finished=True, cancelled=True)}

        def on_chunk(chunk):
            """Observe partial text and the single stop terminal."""
            chunks.append(chunk)
            if chunk.text and not chunk.finished:
                first_text.set()

        client.websocket = messages()
        listener = asyncio.create_task(client._listen())
        try:
            with patch.object(ServiceHandler, "trigger", side_effect=trigger), patch.object(ServiceHandler, "stop_trigger", side_effect=stop):
                pending = asyncio.create_task(client.trigger("first", on_chunk=on_chunk, on_event=events.append))
                await asyncio.wait_for(first_text.wait(), 1)
                await asyncio.wait_for(client.stop(), 1)
                following = asyncio.create_task(client.trigger("next"))
                self.assertEqual(await pending, "hello")
                self.assertEqual(await asyncio.wait_for(following, 1), "pong")
                self.assertEqual(sum(chunk.cancelled for chunk in chunks), 1)
                self.assertTrue(events[-1].cancelled)
                self.assertEqual(events[-1].trigger_id, turns[0])
                await client.stop()
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            await client.websocket.aclose()
            client.websocket = None
            await client.close()


    async def test_http_completion_without_websocket_and_duplicate_event(self):
        from dynamic_agent_client import AgentResponseChunk
        client = DynamicAgentClient()
        client.session_id = "session"
        client.runner_id = "main"
        accepted = asyncio.Event()
        chunks = []

        async def trigger(*args, **kwargs):
            accepted.set()

        async def stop(session_id, trigger_id):
            return {"status": "stopped", "completion": dict(
                type="agent_chunk", runner_id="main", trigger_id=trigger_id,
                text="partial", finished=True, cancelled=True,
            )}

        try:
            with patch.object(ServiceHandler, "trigger", side_effect=trigger), patch.object(ServiceHandler, "stop_trigger", side_effect=stop):
                pending = asyncio.create_task(client.trigger("first", on_chunk=chunks.append))
                await accepted.wait()
                await asyncio.wait_for(client.stop(), 1)
                self.assertEqual(await pending, "partial")
                client._handle_response_chunk(chunks[0])
                self.assertEqual(len(chunks), 1)
        finally:
            await client.close()

    async def test_disconnect_fails_pending_turn(self):
        client = DynamicAgentClient()
        client._trigger_future = asyncio.get_running_loop().create_future()

        async def closed_socket():
            if False:
                yield

        client.websocket = closed_socket()
        await client._listen()
        with self.assertRaisesRegex(ConnectionError, "disconnected"):
            await client._trigger_future
        client.websocket = None
        await client.close()

    async def test_stop_recovers_completion_after_websocket_disconnect(self):
        client = DynamicAgentClient()
        client.session_id = "session"
        client.runner_id = "main"
        client._trigger_id = "turn"
        client._trigger_future = asyncio.get_running_loop().create_future()
        client._trigger_accepted.set()

        async def closed_socket():
            if False:
                yield

        async def stop(*args):
            client.websocket = closed_socket()
            await client._listen()
            return {"completion": dict(type="agent_chunk", trigger_id="turn",
                runner_id="main", text="saved", finished=True, cancelled=True)}

        with patch.object(ServiceHandler, "stop_trigger", side_effect=stop):
            await asyncio.wait_for(client.stop(), 1)
        self.assertEqual(await client._trigger_future, "saved")
        client.websocket = None
        await client.close()
