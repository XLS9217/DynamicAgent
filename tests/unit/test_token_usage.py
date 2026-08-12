import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from dynamic_agent_service.agent.agent_response_handler import AgentResponseHandler
from dynamic_agent_service.logging.log_interface import LogInterface
from dynamic_agent_service.service.service_structs import AgentResponseChunk


class _OpenAIAdapterStub:
    async def async_stream_response(self, messages, tools=None, parallel_tool_calls=False):
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="hello", tool_calls=None))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=5,
                total_tokens=17,
            ),
        )


class TokenUsageTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_usage_is_returned_with_invoke_result(self):
        callback = AsyncMock()
        handler = AgentResponseHandler(_OpenAIAdapterStub())

        result = await handler.invoke(
            messages=[{"role": "user", "content": "hello"}],
            stream_callback=callback,
        )

        self.assertEqual(result.full_text, "hello")
        self.assertEqual(result.prompt_tokens, 12)
        self.assertEqual(result.completion_tokens, 5)
        self.assertEqual(result.total_tokens, 17)
        chunks = [call.args[0] for call in callback.await_args_list]
        self.assertEqual([chunk.prompt_tokens for chunk in chunks], [0, 12])
        self.assertEqual([chunk.completion_tokens for chunk in chunks], [0, 5])
        self.assertEqual([chunk.total_tokens for chunk in chunks], [0, 17])
        self.assertFalse(chunks[-1].invoked)
        self.assertFalse(chunks[-1].finished)

    async def test_handler_appends_normalized_and_detailed_usage(self):
        with patch.object(
            LogInterface,
            "append_invoke_log",
            AsyncMock(return_value="invoke-1"),
        ) as append:
            handler = AgentResponseHandler(
                _OpenAIAdapterStub(),
                log_session_id="session-1",
                runner_id="runner-1",
                parent_runner_id="parent-1",
            )
            result = await handler.invoke(messages=[{"role": "user", "content": "hello"}])

        self.assertEqual(result.total_tokens, 17)
        append.assert_awaited_once_with(
            session_id="session-1",
            runner_id="runner-1",
            parent_runner_id="parent-1",
            messages=[{"role": "user", "content": "hello"}],
            text="hello",
            tool_use=None,
            prompt_tokens=12,
            completion_tokens=5,
            usage_detail={
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            },
        )

    def test_agent_chunk_defaults_preserve_existing_construction(self):
        chunk = AgentResponseChunk(type="agent_chunk", text="hello")

        self.assertEqual(chunk.prompt_tokens, 0)
        self.assertEqual(chunk.completion_tokens, 0)
        self.assertEqual(chunk.total_tokens, 0)
        self.assertIsNone(chunk.runner_id)
        self.assertIsNone(chunk.runner_name)
        self.assertIsNone(chunk.parent_runner_id)


if __name__ == "__main__":
    unittest.main()
