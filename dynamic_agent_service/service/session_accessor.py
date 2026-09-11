"""Session messages are written to PostgreSQL and cached in Redis.

Reads use Redis first and restore the cache from PostgreSQL on a cache miss.
"""
import uuid

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.service_structs import MessageItem


def _messages_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


class SessionAccessor:

    @staticmethod
    async def append_message(
        session_id: str,
        role: str,
        content: str,
    ) -> str:
        """Append one message to PostgreSQL and Redis."""
        item = MessageItem(role=role, content=content)

        message_id = str(uuid.uuid4())
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO session_message (message_id, session_id, role, content)
                VALUES ($1, $2, $3, $4)
                """,
                message_id, session_id, role, content,
            )

        redis = RedisInstance.get_client()
        await redis.rpush(_messages_key(session_id), item.model_dump_json())
        return message_id

    @staticmethod
    async def load_messages(session_id: str) -> list[MessageItem]:
        """Load Redis messages, falling back to PostgreSQL on a cache miss."""
        redis = RedisInstance.get_client()
        raw_list = await redis.lrange(_messages_key(session_id), 0, -1)
        if raw_list:
            return [MessageItem.model_validate_json(raw) for raw in raw_list]

        # Cache miss: load from Postgres and repopulate Redis
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM session_message WHERE session_id = $1 ORDER BY create_at",
                session_id,
            )
        messages = [MessageItem(role=r["role"], content=r["content"]) for r in rows]

        if messages:
            await redis.rpush(_messages_key(session_id), *[m.model_dump_json() for m in messages])

        return messages

    @staticmethod
    async def delete_cached_messages(session_id: str) -> None:
        """Delete only the Redis message list, leaving durable history intact."""
        redis = RedisInstance.get_client()
        await redis.delete(_messages_key(session_id))

    @staticmethod
    async def delete_session(session_id: str) -> None:
        """Delete a session's messages from both Postgres and Redis."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM session_message WHERE session_id = $1", session_id)

        redis = RedisInstance.get_client()
        await redis.delete(_messages_key(session_id))
