"""Initialize the PostgreSQL schema used by Dynamic Agent Service.

Run this module explicitly before starting the service:

    python -m dynamic_agent_service.init_storage
"""

import asyncio

from dotenv import load_dotenv

from dynamic_agent_service.external_service.pg_instance import PgInstance


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bucket (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS blueprint (
    blueprint_id TEXT PRIMARY KEY,
    bucket_name  TEXT NOT NULL REFERENCES bucket(name),
    name         TEXT NOT NULL,
    description  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blueprint_attribute (
    attribute_id  TEXT PRIMARY KEY,
    blueprint_id  TEXT NOT NULL REFERENCES blueprint(blueprint_id),
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    is_identifier BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS blueprint_instance (
    instance_id  TEXT PRIMARY KEY,
    blueprint_id TEXT NOT NULL REFERENCES blueprint(blueprint_id)
);

CREATE TABLE IF NOT EXISTS instance_source (
    source_id       TEXT PRIMARY KEY,
    instance_id     TEXT NOT NULL REFERENCES blueprint_instance(instance_id) ON DELETE CASCADE,
    source_metadata JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS session_message (
    seq        BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_message_session_id
    ON session_message (session_id, seq);

CREATE TABLE IF NOT EXISTS llm_resource (
    resource_id TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    priority    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_llm_resource_enabled
    ON llm_resource (enabled, priority DESC);
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
