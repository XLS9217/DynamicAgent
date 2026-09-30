"""Script name: test_session_storage.py. Check durable writes and cache recovery."""

import json
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.media_storage import MediaStorage
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.session_management import RealtimeSession
from dynamic_agent_service.service.service_structs import (
    CreateSessionRequest,
    MessageItem,
    StoredImagePart,
)


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
        self.redis.delete = AsyncMock()
        self.session = RealtimeSession("test", session_type="chat", session_id="test-session")

    def test_create_request_defaults_to_task(self):
        """Omitted session_type must select Redis-only task storage."""
        self.assertEqual(CreateSessionRequest(setting="test").session_type, "task")

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
            arguments = self.connection.execute.await_args_list[index].args
            self.assertEqual(arguments[1:3], (ids[index], "test-session"))
            self.assertEqual(
                MessageItem.model_validate_json(arguments[3]).public_message(),
                {"role": role, "content": role + " text"},
            )
            key, payload = self.redis.rpush.await_args_list[index].args
            self.assertEqual(key, "session:chat:test-session:messages")
            self.assertEqual(
                MessageItem.model_validate_json(payload).public_message(),
                {"role": role, "content": role + " text"},
            )

    async def test_cache_miss_restores_both_roles_from_database(self):
        """Ensure database history repopulates an empty cache."""
        expected = [{"role": "user", "content": "question"}, {"role": "assistant", "content": "answer"}]
        self.connection.fetch.return_value = [
            {"content": MessageItem.from_text(item["role"], item["content"]).model_dump_json()}
            for item in expected
        ]
        with (
            patch.object(PgInstance, "get_pool", return_value=self.pool),
            patch.object(RedisInstance, "get_client", return_value=self.redis),
        ):
            self.assertEqual(await self.session.load_messages(), expected)
        self.assertEqual(
            [MessageItem.model_validate_json(v).public_message() for v in self.redis.rpush.await_args.args[1:]],
            expected,
        )

    async def test_cache_hit_does_not_read_database(self):
        """Ensure cached history avoids a database read."""
        expected = {"role": "assistant", "content": "cached"}
        self.redis.lrange.return_value = [MessageItem.from_text("assistant", "cached").model_dump_json()]
        with (
            patch.object(PgInstance, "get_pool") as get_pool,
            patch.object(RedisInstance, "get_client", return_value=self.redis),
        ):
            self.assertEqual(await self.session.load_messages(), [expected])
        get_pool.assert_not_called()

    async def test_task_messages_use_only_redis(self):
        """Default task sessions must never acquire PostgreSQL for messages."""
        task = RealtimeSession("test", session_id="task-session")
        with (
            patch.object(PgInstance, "get_pool") as get_pool,
            patch.object(RedisInstance, "get_client", return_value=self.redis),
        ):
            message_id = await task.append_message("user", "temporary")
            self.assertEqual(await task.load_messages(), [])

        self.assertTrue(message_id)
        get_pool.assert_not_called()
        key, payload = self.redis.rpush.await_args.args
        self.assertEqual(key, "session:task:task-session:messages")
        self.assertEqual(
            MessageItem.model_validate_json(payload).public_message(),
            {"role": "user", "content": "temporary"},
        )

    async def test_task_cleanup_deletes_referenced_media_before_redis(self):
        """Task cleanup must not orphan files after removing their only references."""
        image = StoredImagePart(
            media_id=uuid4(),
            relative_path="ab/image.png",
            mime_type="image/png",
            byte_size=8,
            sha256="0" * 64,
        )
        self.redis.lrange.return_value = [MessageItem.from_user("image", [image]).model_dump_json()]
        with (
            patch.object(RedisInstance, "get_client", return_value=self.redis),
            patch.object(MediaStorage, "delete", new_callable=AsyncMock) as delete_media,
        ):
            await SessionAccessor.delete_cached_messages(
                "task-session",
                "task",
                delete_media=True,
            )

        delete_media.assert_awaited_once_with([image])
        self.redis.delete.assert_awaited_once_with(
            "session:task:task-session:messages",
            "session:task:task-session:meta",
        )
