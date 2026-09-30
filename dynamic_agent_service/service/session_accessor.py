"""Session message documents are written to PostgreSQL and cached in Redis.

Reads use Redis first and restore the cache from PostgreSQL on a cache miss.
"""
import json
import uuid

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.media_storage import MediaStorage
from dynamic_agent_service.service.service_structs import MessageItem, SessionMeta, StoredImagePart


def _messages_key(session_id: str, session_type: str) -> str:
    return f"session:{session_type}:{session_id}:messages"


def _meta_key(session_id: str, session_type: str) -> str:
    return f"session:{session_type}:{session_id}:meta"


def _legacy_messages_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


class SessionAccessor:

    @staticmethod
    async def append_message(
        session_id: str,
        item: MessageItem,
        session_type: str,
    ) -> str:
        """Append a message to Redis and persist chat messages in PostgreSQL."""
        message_id = str(uuid.uuid4())
        if session_type == "chat":
            pool = PgInstance.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO session_message (message_id, session_id, content)
                    VALUES ($1, $2, $3::jsonb)
                    """,
                    message_id, session_id, item.model_dump_json(),
                )

        redis = RedisInstance.get_client()
        await redis.rpush(_messages_key(session_id, session_type), item.model_dump_json())
        return message_id

    @staticmethod
    async def load_messages(session_id: str, session_type: str) -> list[MessageItem]:
        """Load Redis history and restore chat history from PostgreSQL."""
        redis = RedisInstance.get_client()
        key = _messages_key(session_id, session_type)
        raw_list = await redis.lrange(key, 0, -1)
        if raw_list:
            return [MessageItem.model_validate_json(raw) for raw in raw_list]

        if session_type == "task":
            return []

        # Migrate the previous chat cache namespace when present.
        legacy = await redis.lrange(_legacy_messages_key(session_id), 0, -1)
        if legacy:
            await redis.rpush(key, *legacy)
            await redis.delete(_legacy_messages_key(session_id))
            return [MessageItem.model_validate_json(raw) for raw in legacy]

        # Cache miss: load from Postgres and repopulate Redis
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT content FROM session_message WHERE session_id = $1 ORDER BY create_at, message_id",
                session_id,
            )
        messages = [SessionAccessor._parse_content(row["content"]) for row in rows]

        if messages:
            await redis.rpush(key, *[m.model_dump_json() for m in messages])

        return messages

    @staticmethod
    async def delete_cached_messages(
        session_id: str,
        session_type: str,
        delete_media: bool = False,
    ) -> None:
        """Delete Redis state and optionally its referenced media files."""
        redis = RedisInstance.get_client()
        key = _messages_key(session_id, session_type)
        raw_list = await redis.lrange(key, 0, -1) if delete_media else []
        if delete_media:
            await MediaStorage.delete(SessionAccessor._images_from_values(raw_list))
        keys = [key, _meta_key(session_id, session_type)]
        if session_type == "chat":
            keys.append(_legacy_messages_key(session_id))
        await redis.delete(*keys)

    @staticmethod
    async def delete_session(session_id: str, session_type: str) -> None:
        """Delete storage owned by one chat or task session."""
        if session_type == "task":
            await SessionAccessor.delete_cached_messages(session_id, session_type, delete_media=True)
            return

        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT content FROM session_message WHERE session_id = $1",
                session_id,
            )
            await conn.execute("DELETE FROM session_message WHERE session_id = $1", session_id)
        await SessionAccessor.delete_cached_messages(session_id, session_type)
        await MediaStorage.delete(SessionAccessor._images_from_values([row["content"] for row in rows]))

    @staticmethod
    async def save_meta(meta: SessionMeta) -> None:
        """Store session type and reconnect metadata in Redis."""
        redis = RedisInstance.get_client()
        await redis.set(_meta_key(meta.session_id, meta.session_type), meta.model_dump_json())

    @staticmethod
    async def load_meta(session_id: str) -> SessionMeta | None:
        """Load metadata from either session namespace."""
        redis = RedisInstance.get_client()
        for session_type in ("task", "chat"):
            raw = await redis.get(_meta_key(session_id, session_type))
            if raw:
                return SessionMeta.model_validate_json(raw)
        return None

    @staticmethod
    async def has_persisted_messages(session_id: str) -> bool:
        """Check whether an ID already owns durable chat history."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            return bool(await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM session_message WHERE session_id = $1)",
                session_id,
            ))

    @staticmethod
    def _images_from_values(values: list[str | bytes | dict]) -> list[StoredImagePart]:
        """Extract stored image references from message documents."""
        return [
            part
            for value in values
            for part in SessionAccessor._parse_content(value).parts
            if isinstance(part, StoredImagePart)
        ]

    @staticmethod
    def _parse_content(value: str | bytes | dict) -> MessageItem:
        """Validate JSONB returned as either decoded data or a JSON string."""
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return MessageItem.model_validate(json.loads(value) if isinstance(value, str) else value)
