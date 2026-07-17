import uuid

from dynamic_agent_service.agent.llm_resource_structs import (
    LLMResource,
    LLMResourceCreate,
    LLMResourceUpdate,
)
from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance


class LLMResourceAccessor(DataAccessor):
    """PostgreSQL access for OpenAI-compatible LLM endpoint resources."""

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
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
            """)
        return True

    @staticmethod
    async def create_resource(resource: LLMResourceCreate) -> LLMResource:
        resource_id = str(uuid.uuid4())
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_resource (
                    resource_id, model, api_key, base_url, enabled, priority
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING resource_id, model, api_key, base_url, enabled, priority
                """,
                resource_id,
                resource.model,
                resource.api_key,
                resource.base_url,
                resource.enabled,
                resource.priority,
            )
        return LLMResource(**dict(row))

    @staticmethod
    async def get_resource(resource_id: str) -> LLMResource | None:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT resource_id, model, api_key, base_url, enabled, priority
                FROM llm_resource
                WHERE resource_id = $1
                """,
                resource_id,
            )
        return LLMResource(**dict(row)) if row is not None else None

    @staticmethod
    async def list_resources(enabled_only: bool = True) -> list[LLMResource]:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            if enabled_only:
                rows = await conn.fetch(
                    """
                    SELECT resource_id, model, api_key, base_url, enabled, priority
                    FROM llm_resource
                    WHERE enabled = TRUE
                    ORDER BY priority DESC, resource_id
                    """
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT resource_id, model, api_key, base_url, enabled, priority
                    FROM llm_resource
                    ORDER BY priority DESC, resource_id
                    """
                )
        return [LLMResource(**dict(row)) for row in rows]

    @staticmethod
    async def set_enabled(resource_id: str, enabled: bool) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE llm_resource
                SET enabled = $2
                WHERE resource_id = $1
                """,
                resource_id,
                enabled,
            )
        return result == "UPDATE 1"

    @staticmethod
    async def set_priority(resource_id: str, priority: int) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE llm_resource
                SET priority = $2
                WHERE resource_id = $1
                """,
                resource_id,
                priority,
            )
        return result == "UPDATE 1"

    @staticmethod
    async def update_resource(resource_id: str, update: LLMResourceUpdate) -> LLMResource | None:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE llm_resource
                SET model = COALESCE($2, model),
                    api_key = COALESCE($3, api_key),
                    base_url = COALESCE($4, base_url),
                    enabled = COALESCE($5, enabled),
                    priority = COALESCE($6, priority)
                WHERE resource_id = $1
                RETURNING resource_id, model, api_key, base_url, enabled, priority
                """,
                resource_id,
                update.model,
                update.api_key,
                update.base_url,
                update.enabled,
                update.priority,
            )
        return LLMResource(**dict(row)) if row is not None else None

    @staticmethod
    async def delete_resource(resource_id: str) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM llm_resource WHERE resource_id = $1",
                resource_id,
            )
        return result == "DELETE 1"
