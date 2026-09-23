"""Script name: migrate_session_messages.py. Convert text session rows to JSONB documents."""

import asyncio

from dotenv import load_dotenv

from dynamic_agent_service.external_service.pg_instance import PgInstance


MIGRATION_SQL = """
ALTER TABLE session_message ADD COLUMN content_v2 JSONB;

UPDATE session_message
SET content_v2 = jsonb_build_object(
    'version', 1,
    'role', role,
    'parts', jsonb_build_array(
        jsonb_build_object('type', 'text', 'text', content)
    )
);

ALTER TABLE session_message ALTER COLUMN content_v2 SET NOT NULL;
ALTER TABLE session_message DROP COLUMN content;
ALTER TABLE session_message DROP COLUMN role;
ALTER TABLE session_message RENAME COLUMN content_v2 TO content;
DROP INDEX IF EXISTS idx_session_message_session_id;
CREATE INDEX IF NOT EXISTS idx_session_message_history
    ON session_message (session_id, create_at, message_id);
ALTER TABLE session_message ADD CONSTRAINT session_message_content_is_object
    CHECK (jsonb_typeof(content) = 'object');
"""


async def migrate() -> bool:
    """Apply the old-text to JSONB migration once and reject unknown schemas."""
    pool = PgInstance.get_pool()
    async with pool.acquire() as connection:
        columns = await connection.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'session_message'
        """)
        shape = {row["column_name"]: row["data_type"] for row in columns}
        if shape.get("content") == "jsonb" and "role" not in shape:
            return False
        if shape.get("content") != "text" or shape.get("role") != "text":
            raise RuntimeError(f"Unsupported session_message schema: {shape}")
        async with connection.transaction():
            await connection.execute(MIGRATION_SQL)
    return True


async def main() -> None:
    """Load configuration, run the migration, and close PostgreSQL cleanly."""
    load_dotenv()
    await PgInstance.initialize()
    try:
        changed = await migrate()
        print("session_message migrated" if changed else "session_message already current")
    finally:
        await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
