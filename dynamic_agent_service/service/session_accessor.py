"""
Session accessor for session message persistence.

Postgres is the durable source of truth; Redis is a live cache.
- append: write to Postgres and Redis
- load: read Redis first, fall back to Postgres (and repopulate Redis on miss)
"""
from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.service_structs import MessageItem


def _messages_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


class SessionAccessor(DataAccessor):

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        """Initialize the PostgreSQL table for session messages."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_message (
                    seq        BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_message_session_id
                    ON session_message (session_id, seq);
            """)
        return True

    @staticmethod
    async def append_message(session_id: str, role: str, content: str) -> None:
        """Append one message to both Postgres (durable) and Redis (cache)."""
        item = MessageItem(role=role, content=content)

        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO session_message (session_id, role, content) VALUES ($1, $2, $3)",
                session_id, role, content,
            )

        redis = RedisInstance.get_client()
        await redis.rpush(_messages_key(session_id), item.model_dump_json())

    @staticmethod
    async def load_messages(session_id: str) -> list[MessageItem]:
        """Load a session's messages: Redis first, fall back to Postgres."""
        redis = RedisInstance.get_client()
        raw_list = await redis.lrange(_messages_key(session_id), 0, -1)
        if raw_list:
            return [MessageItem.model_validate_json(raw) for raw in raw_list]

        # Cache miss: load from Postgres and repopulate Redis
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM session_message WHERE session_id = $1 ORDER BY seq",
                session_id,
            )
        messages = [MessageItem(role=r["role"], content=r["content"]) for r in rows]

        if messages:
            await redis.rpush(_messages_key(session_id), *[m.model_dump_json() for m in messages])

        return messages

    @staticmethod
    async def delete_session(session_id: str) -> None:
        """Delete a session's messages from both Postgres and Redis."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM session_message WHERE session_id = $1", session_id)

        redis = RedisInstance.get_client()
        await redis.delete(_messages_key(session_id))