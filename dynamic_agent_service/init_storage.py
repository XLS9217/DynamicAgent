"""Initialize the PostgreSQL schema used by Dynamic Agent Service.

DO NOT ALTER TABLE HERE!
need to make sure it gives the exact tables I need

Run this module explicitly before starting the service:

    python -m dynamic_agent_service.init_storage
"""

import asyncio

from dotenv import load_dotenv

from dynamic_agent_service.external_service.pg_instance import PgInstance


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_message (
    message_id UUID PRIMARY KEY,
    create_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id TEXT NOT NULL,
    content    JSONB NOT NULL,
    sequence_no BIGINT GENERATED ALWAYS AS IDENTITY,
    UNIQUE (session_id, message_id),
    CONSTRAINT session_message_content_is_object
        CHECK (jsonb_typeof(content) = 'object')
);

CREATE INDEX IF NOT EXISTS session_message_sequence ON session_message(session_id, sequence_no);

CREATE INDEX IF NOT EXISTS idx_session_message_history
    ON session_message (session_id, create_at, message_id);

CREATE TABLE IF NOT EXISTS session_memory_checkpoint (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL CHECK (btrim(summary) <> ''),
    compacted TEXT NOT NULL CHECK (btrim(compacted) <> ''),
    last_message_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, last_message_id),
    FOREIGN KEY (session_id, last_message_id)
        REFERENCES session_message (session_id, message_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS openai_resource (
    resource_id TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    bypass_proxy BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at  TIMESTAMPTZ,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    priority    INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT openai_resource_deleted_disabled
        CHECK (deleted_at IS NULL OR enabled = FALSE)
);

CREATE INDEX IF NOT EXISTS idx_openai_resource_enabled
    ON openai_resource (enabled, priority DESC);

"""


async def initialize_storage() -> None:
    """Apply the complete service schema to an initialized PostgreSQL pool."""
    pool = PgInstance.get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(SCHEMA_SQL)


async def main() -> None:
    load_dotenv()
    await PgInstance.initialize()
    try:
        await initialize_storage()
    finally:
        await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
