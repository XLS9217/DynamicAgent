import time
import unittest
from unittest.mock import AsyncMock, patch

from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.session_management import RealtimeSession, RealtimeSessionManager


class SessionCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_sessions = RealtimeSessionManager._sessions
        RealtimeSessionManager._sessions = {}

    async def asyncTearDown(self):
        RealtimeSessionManager._sessions = self.original_sessions

    async def test_cleanup_removes_expired_sessions_and_redis_messages(self):
        expired_first = RealtimeSession(
            "test",
            reconnect_keep=1,
            session_id="expired-first",
        )
        expired_second = RealtimeSession(
            "test",
            reconnect_keep=1,
            session_id="expired-second",
        )
        active = RealtimeSession(
            "test",
            reconnect_keep=1,
            session_id="active",
        )

        expired_at = time.time() - 2
        expired_first.disconnect_time = expired_at
        expired_second.disconnect_time = expired_at
        active.disconnect_time = None
        RealtimeSessionManager._sessions = {
            expired_first.session_id: expired_first,
            expired_second.session_id: expired_second,
            active.session_id: active,
        }

        with patch.object(
            SessionAccessor,
            "delete_cached_messages",
            new_callable=AsyncMock,
        ) as delete_cached_messages:
            await RealtimeSessionManager.cleanup_expired()

        self.assertIsNone(RealtimeSessionManager.get(expired_first.session_id))
        self.assertIsNone(RealtimeSessionManager.get(expired_second.session_id))
        self.assertIs(RealtimeSessionManager.get(active.session_id), active)
        self.assertCountEqual(
            [call.args[0] for call in delete_cached_messages.await_args_list],
            [expired_first.session_id, expired_second.session_id],
        )

    async def test_cleanup_preserves_session_during_reconnect_window(self):
        reconnecting = RealtimeSession(
            "test",
            reconnect_keep=30,
            session_id="reconnecting",
        )
        reconnecting.disconnect_time = time.time()
        RealtimeSessionManager._sessions = {reconnecting.session_id: reconnecting}

        with patch.object(
            SessionAccessor,
            "delete_cached_messages",
            new_callable=AsyncMock,
        ) as delete_cached_messages:
            await RealtimeSessionManager.cleanup_expired()

        self.assertIs(RealtimeSessionManager.get(reconnecting.session_id), reconnecting)
        delete_cached_messages.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
