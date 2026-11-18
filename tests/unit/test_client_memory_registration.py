"""Verify chat-only memory registration without a live service."""
import unittest
from unittest.mock import AsyncMock, patch

from dynamic_agent_client import DynamicAgentChatClient, DynamicAgentClient, DynamicAgentTaskClient
from dynamic_agent_client.operator import MemoryOperator
from dynamic_agent_client.service_handler import ServiceHandler


class ClientMemoryRegistrationTests(unittest.IsolatedAsyncioTestCase):
    """Keep task tools explicit while retaining chat memory."""

    async def check_registration(self, client_type, expected_type, **kwargs):
        """Exercise session creation with isolated transport and registration."""
        async def create_session(setting, instance, **options):
            return options.get('session_id') or 'new-session', options['session_type'], 'runner', None, []

        with patch.object(ServiceHandler, 'create_session', side_effect=create_session), \
             patch.object(DynamicAgentClient, '_listen', new_callable=AsyncMock), \
             patch.object(DynamicAgentClient, 'add_operator', new_callable=AsyncMock) as register:
            client = await client_type.create('test', **kwargs)
            await client._listen_task
            self.assertEqual(client.session_type, expected_type)
            if expected_type == 'chat':
                register.assert_awaited_once()
                self.assertIsInstance(register.await_args.args[0], MemoryOperator)
            else:
                register.assert_not_awaited()

    async def test_chat_registers_memory_on_create_and_restore(self):
        """Chats retain memory tools for both new and restored sessions."""
        await self.check_registration(DynamicAgentChatClient, 'chat')
        await self.check_registration(DynamicAgentChatClient, 'chat', session_id='restored')

    async def test_task_never_registers_memory_implicitly(self):
        """Task agents receive only caller-provided operators."""
        await self.check_registration(DynamicAgentTaskClient, 'task')
        await self.check_registration(DynamicAgentTaskClient, 'task', session_id='restored')

    async def test_generic_client_obeys_session_type(self):
        """The generic entry point follows the same session policy."""
        await self.check_registration(DynamicAgentClient, 'task')
        await self.check_registration(DynamicAgentClient, 'chat', session_type='chat')
