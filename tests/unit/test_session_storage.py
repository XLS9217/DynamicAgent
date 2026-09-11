"""Script name: test_session_storage.py. Check durable writes and cache recovery."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.session_management import RealtimeSession


class SessionStorageTest(unittest.IsolatedAsyncioTestCase):
    """Verify session persistence without touching external services."""

    def setUp(self):
        """Create isolated database and cache doubles."""
        self.connection = MagicMock()
        self.connection.execute = AsyncMock()
        self.connection.fetch = AsyncMock()
        self.pool = MagicMock()
        self.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=self.connection)
        self.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        self.redis = MagicMock()
        self.redis.rpush = AsyncMock()
        self.redis.lrange = AsyncMock(return_value=[])
        self.session = RealtimeSession("test", session_id="test-session")

    async def test_user_and_assistant_messages_are_both_persisted(self):
        """Ensure both conversation roles reach PostgreSQL and Redis."""
        with (
            patch.object(PgInstance, "get_pool", return_value=self.pool),
            patch.object(RedisInstance, "get_client", return_value=self.redis),
        ):
            ids = [await self.session.append_message(role, role + " text") for role in ["user", "assistant"]]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.connection.execute.await_count, 2)
        for index, role in enumerate(["user", "assistant"]):
            self.assertEqual(self.connection.execute.await_args_list[index].args[1:], (ids[index], "test-session", role, role + " text"))
            key, payload = self.redis.rpush.await_args_list[index].args
            self.assertEqual(key, "session:test-session:messages")
            self.assertEqual(json.loads(payload), {"role": role, "content": role + " text"})

    async def test_cache_miss_restores_both_roles_from_database(self):
        """Ensure database history repopulates an empty cache."""
        expected = [{"role": "user", "content": "question"}, {"role": "assistant", "content": "answer"}]
        self.connection.fetch.return_value = expected
        with (
            patch.object(PgInstance, "get_pool", return_value=self.pool),
            patch.object(RedisInstance, "get_client", return_value=self.redis),
        ):
            self.assertEqual(await self.session.load_messages(), expected)
        self.assertEqual([json.loads(v) for v in self.redis.rpush.await_args.args[1:]], expected)

    async def test_cache_hit_does_not_read_database(self):
        """Ensure cached history avoids a database read."""
        expected = {"role": "assistant", "content": "cached"}
        self.redis.lrange.return_value = [json.dumps(expected)]
        with (
            patch.object(PgInstance, "get_pool") as get_pool,
            patch.object(RedisInstance, "get_client", return_value=self.redis),
        ):
            self.assertEqual(await self.session.load_messages(), [expected])
        get_pool.assert_not_called()
