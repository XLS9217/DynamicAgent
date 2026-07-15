"""Reusable helpers for checking session-message storage in integration tests."""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.service_structs import MessageItem


__all__ = [
    "SessionStorageSnapshot",
    "assert_session_deleted",
    "assert_session_persisted",
    "assert_session_redis_only",
    "get_postgres_session_messages",
    "get_redis_session_messages",
    "get_session_storage",
    "session_exists_in_postgres",
    "session_exists_in_redis",
    "session_messages_key",
    "storage_connections",
    "wait_for_session_deleted",
]


def session_messages_key(session_id: str) -> str:
    """Return the Redis key used for a session's message list."""
    return f"session:{session_id}:messages"


@dataclass(frozen=True)
class SessionStorageSnapshot:
    """Message state for one session across PostgreSQL and Redis."""

    session_id: str
    postgres_messages: list[MessageItem]
    redis_messages: list[MessageItem]
    redis_ttl: int

    @property
    def exists_in_postgres(self) -> bool:
        return bool(self.postgres_messages)

    @property
    def exists_in_redis(self) -> bool:
        return bool(self.redis_messages)


@asynccontextmanager
async def storage_connections() -> AsyncIterator[None]:
    """
    Ensure storage clients are initialized for a test.

    Connections that were already initialized are left open. Connections created
    by this context manager are closed on exit.
    """
    opened_postgres = PgInstance._pool is None
    opened_redis = RedisInstance._client is None

    if opened_postgres:
        await PgInstance.initialize()
    try:
        if opened_redis:
            await RedisInstance.initialize()
        try:
            yield
        finally:
            if opened_redis:
                await RedisInstance.close()
    finally:
        if opened_postgres:
            await PgInstance.close()


async def get_postgres_session_messages(session_id: str) -> list[MessageItem]:
    """Read a session's durable messages directly from PostgreSQL."""
    pool = PgInstance.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM session_message
            WHERE session_id = $1
            ORDER BY seq
            """,
            session_id,
        )
    return [MessageItem(role=row["role"], content=row["content"]) for row in rows]


async def get_redis_session_messages(session_id: str) -> list[MessageItem]:
    """Read a session's live message list directly from Redis."""
    redis = RedisInstance.get_client()
    values = await redis.lrange(session_messages_key(session_id), 0, -1)
    return [MessageItem.model_validate_json(value) for value in values]


async def get_session_storage(session_id: str) -> SessionStorageSnapshot:
    """Capture PostgreSQL messages, Redis messages, and the Redis TTL."""
    postgres_messages, redis_messages = await asyncio.gather(
        get_postgres_session_messages(session_id),
        get_redis_session_messages(session_id),
    )
    redis = RedisInstance.get_client()
    redis_ttl = await redis.ttl(session_messages_key(session_id))
    return SessionStorageSnapshot(
        session_id=session_id,
        postgres_messages=postgres_messages,
        redis_messages=redis_messages,
        redis_ttl=redis_ttl,
    )


async def session_exists_in_postgres(session_id: str) -> bool:
    """Return whether PostgreSQL contains any messages for the session."""
    return bool(await get_postgres_session_messages(session_id))


async def session_exists_in_redis(session_id: str) -> bool:
    """Return whether Redis contains a message list for the session."""
    redis = RedisInstance.get_client()
    return bool(await redis.exists(session_messages_key(session_id)))


def _message_dicts(messages: Sequence[MessageItem]) -> list[dict[str, str]]:
    return [message.model_dump() for message in messages]


def _expected_message_dicts(
    messages: Sequence[MessageItem | Mapping[str, str]],
) -> list[dict[str, str]]:
    return [
        message.model_dump() if isinstance(message, MessageItem) else dict(message)
        for message in messages
    ]


async def assert_session_persisted(
    session_id: str,
    expected_messages: Sequence[MessageItem | Mapping[str, str]] | None = None,
) -> SessionStorageSnapshot:
    """Assert that durable and Redis message lists exist and match."""
    snapshot = await get_session_storage(session_id)
    postgres = _message_dicts(snapshot.postgres_messages)
    redis = _message_dicts(snapshot.redis_messages)

    assert postgres, f"session {session_id!r} has no PostgreSQL messages"
    assert redis, f"session {session_id!r} has no Redis messages"
    assert postgres == redis, (
        f"session {session_id!r} differs across storage: "
        f"PostgreSQL={postgres!r}, Redis={redis!r}"
    )
    if expected_messages is not None:
        expected = _expected_message_dicts(expected_messages)
        assert postgres == expected, (
            f"session {session_id!r} messages differ: expected={expected!r}, actual={postgres!r}"
        )
    return snapshot


async def assert_session_redis_only(
    session_id: str,
    expected_messages: Sequence[MessageItem | Mapping[str, str]] | None = None,
) -> SessionStorageSnapshot:
    """Assert that a session exists in Redis and has no PostgreSQL messages."""
    snapshot = await get_session_storage(session_id)
    postgres = _message_dicts(snapshot.postgres_messages)
    redis = _message_dicts(snapshot.redis_messages)

    assert not postgres, (
        f"session {session_id!r} unexpectedly has PostgreSQL messages: {postgres!r}"
    )
    assert redis, f"session {session_id!r} has no Redis messages"
    if expected_messages is not None:
        expected = _expected_message_dicts(expected_messages)
        assert redis == expected, (
            f"session {session_id!r} Redis messages differ: expected={expected!r}, actual={redis!r}"
        )
    return snapshot


async def assert_session_deleted(session_id: str) -> SessionStorageSnapshot:
    """Assert that neither PostgreSQL nor Redis contains session messages."""
    snapshot = await get_session_storage(session_id)
    postgres = _message_dicts(snapshot.postgres_messages)
    redis = _message_dicts(snapshot.redis_messages)
    assert not postgres, (
        f"session {session_id!r} still has PostgreSQL messages: {postgres!r}"
    )
    assert not redis, f"session {session_id!r} still has Redis messages: {redis!r}"
    return snapshot


async def wait_for_session_deleted(
    session_id: str,
    timeout: float = 10.0,
    interval: float = 0.1,
) -> SessionStorageSnapshot:
    """Wait until both backends are empty, useful for Redis TTL assertions."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_snapshot = await get_session_storage(session_id)

    while last_snapshot.exists_in_postgres or last_snapshot.exists_in_redis:
        if loop.time() >= deadline:
            raise AssertionError(
                f"session {session_id!r} was not deleted within {timeout}s; "
                f"last snapshot={last_snapshot!r}"
            )
        await asyncio.sleep(interval)
        last_snapshot = await get_session_storage(session_id)

    return last_snapshot
