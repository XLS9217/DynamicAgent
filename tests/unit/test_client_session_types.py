import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, patch

from dynamic_agent_client import (
    DynamicAgentChatClient,
    DynamicAgentClient,
    DynamicAgentTaskClient,
)
from dynamic_agent_client.service_handler import ServiceHandler


class _EmptyWebSocket:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def close(self):
        pass


class ClientSessionTypesTest(unittest.IsolatedAsyncioTestCase):
    async def test_specialized_trigger_delegates_to_base_client(self):
        base_trigger = AsyncMock(return_value="answer")
        with patch.object(DynamicAgentClient, "trigger", base_trigger):
            result = await DynamicAgentChatClient().trigger("hello")

        self.assertEqual(result, "answer")
        base_trigger.assert_awaited_once_with("hello", None, None, None)

    async def test_specialized_clients_extend_base_and_select_storage_policy(self):
        self.assertTrue(issubclass(DynamicAgentChatClient, DynamicAgentClient))
        self.assertTrue(issubclass(DynamicAgentTaskClient, DynamicAgentClient))
        self.assertEqual(DynamicAgentChatClient.__module__, "dynamic_agent_client.chat_client")
        self.assertEqual(DynamicAgentTaskClient.__module__, "dynamic_agent_client.task_client")
        self.assertIn("trigger", DynamicAgentChatClient.__dict__)
        self.assertIn("trigger", DynamicAgentTaskClient.__dict__)
        self.assertNotIn("session_type", inspect.signature(DynamicAgentChatClient.create).parameters)
        self.assertNotIn("session_type", inspect.signature(DynamicAgentTaskClient.create).parameters)

        create_session = AsyncMock(side_effect=[
            ("chat-id", "chat", "runner", _EmptyWebSocket(), []),
            ("task-id", "task", "runner", _EmptyWebSocket(), []),
        ])
        with patch.object(ServiceHandler, "create_session", create_session):
            chat = await DynamicAgentChatClient.create("chat setting")
            task = await DynamicAgentTaskClient.create("task setting")
            await asyncio.sleep(0)

        self.assertIsInstance(chat, DynamicAgentChatClient)
        self.assertEqual(chat.session_type, "chat")
        self.assertIsInstance(task, DynamicAgentTaskClient)
        self.assertEqual(task.session_type, "task")
        self.assertEqual(create_session.await_args_list[0].kwargs["session_type"], "chat")
        self.assertEqual(create_session.await_args_list[1].kwargs["session_type"], "task")

        await chat.close()
        await task.close()


if __name__ == "__main__":
    unittest.main()
