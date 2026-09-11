"""Check expiration using local session state and rolled-back PostgreSQL writes."""
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from dotenv import load_dotenv

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.session_management import RealtimeSession, RealtimeSessionManager
from tests.test_util.storage_check import assert_session_persisted, get_session_storage, storage_connections

load_dotenv()


class SessionStorageCleanupIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_expiration_removes_cache_but_preserves_history(self):
        session_id = f"integration-cleanup-{uuid.uuid4()}"
        expected = [{"role": "user", "content": "test message"}]
        async with storage_connections():
            async with PgInstance.get_pool().acquire() as connection:
                transaction = connection.transaction()
                await transaction.start()
                pool = MagicMock()
                pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
                pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
                session = RealtimeSession("test", reconnect_keep=1, session_id=session_id)
                session.disconnect_time = time.time() - 2
                try:
                    with (
                        patch.object(PgInstance, "get_pool", return_value=pool),
                        patch.object(RealtimeSessionManager, "_sessions", {session_id: session}),
                    ):
                        await session.append_message("user", "test message")
                        await assert_session_persisted(session_id, expected)
                        await RealtimeSessionManager.cleanup_expired()
                        self.assertIsNone(RealtimeSessionManager.get(session_id))
                        snapshot = await get_session_storage(session_id)
                        self.assertEqual(snapshot.redis_messages, [])
                        self.assertEqual([m.model_dump() for m in snapshot.postgres_messages], expected)
                        self.assertEqual(await session.load_messages(), expected)
                        await assert_session_persisted(session_id, expected)
                finally:
                    try:
                        await SessionAccessor.delete_cached_messages(session_id)
                    finally:
                        await transaction.rollback()
