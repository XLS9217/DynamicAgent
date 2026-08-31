import uuid

from dynamic_agent_service.external_service.openai_resource_structs import (
    OpenAIResource,
    OpenAIResourceCreate,
    OpenAIResourceUpdate,
)
from dynamic_agent_service.external_service.pg_instance import PgInstance


class OpenAIResourceAccessor:
    """PostgreSQL access for OpenAI-compatible API resources."""

    @staticmethod
    async def create_resource(resource: OpenAIResourceCreate) -> OpenAIResource:
        resource_id = str(uuid.uuid4())
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO openai_resource (
                    resource_id, model, api_key, base_url, enabled, priority
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING resource_id, model, api_key, base_url, deleted_at, enabled, priority
                """,
                resource_id,
                resource.model,
                resource.api_key,
                resource.base_url,
                resource.enabled,
                resource.priority,
            )
        return OpenAIResource(**dict(row))

    @staticmethod
    async def get_resource(resource_id: str) -> OpenAIResource | None:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT resource_id, model, api_key, base_url, deleted_at, enabled, priority
                FROM openai_resource
                WHERE resource_id = $1
                """,
                resource_id,
            )
        return OpenAIResource(**dict(row)) if row is not None else None

    @staticmethod
    async def get_active_resource() -> OpenAIResource | None:
        """Return the highest-priority enabled resource for new invocations."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT resource_id, model, api_key, base_url, deleted_at, enabled, priority
                FROM openai_resource
                WHERE enabled = TRUE AND deleted_at IS NULL
                ORDER BY priority DESC, resource_id
                LIMIT 1
                """
            )
        return OpenAIResource(**dict(row)) if row is not None else None

    @staticmethod
    async def list_resources(enabled_only: bool = True) -> list[OpenAIResource]:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            if enabled_only:
                rows = await conn.fetch(
                    """
                    SELECT resource_id, model, api_key, base_url, deleted_at, enabled, priority
                    FROM openai_resource
                    WHERE enabled = TRUE AND deleted_at IS NULL
                    ORDER BY priority DESC, resource_id
                    """
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT resource_id, model, api_key, base_url, deleted_at, enabled, priority
                    FROM openai_resource
                    WHERE deleted_at IS NULL
                    ORDER BY priority DESC, resource_id
                    """
                )
        return [OpenAIResource(**dict(row)) for row in rows]

    @staticmethod
    async def set_enabled(resource_id: str, enabled: bool) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE openai_resource
                SET enabled = $2
                WHERE resource_id = $1 AND deleted_at IS NULL
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
                UPDATE openai_resource
                SET priority = $2
                WHERE resource_id = $1
                """,
                resource_id,
                priority,
            )
        return result == "UPDATE 1"

    @staticmethod
    async def update_resource(
        resource_id: str,
        update: OpenAIResourceUpdate,
    ) -> OpenAIResource | None:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE openai_resource
                SET model = COALESCE($2, model),
                    api_key = COALESCE($3, api_key),
                    base_url = COALESCE($4, base_url),
                    enabled = COALESCE($5, enabled),
                    priority = COALESCE($6, priority)
                WHERE resource_id = $1 AND deleted_at IS NULL
                RETURNING resource_id, model, api_key, base_url, deleted_at, enabled, priority
                """,
                resource_id,
                update.model,
                update.api_key,
                update.base_url,
                update.enabled,
                update.priority,
            )
        return OpenAIResource(**dict(row)) if row is not None else None

    @staticmethod
    async def delete_resource(resource_id: str) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE openai_resource
                SET deleted_at = COALESCE(deleted_at, NOW()), enabled = FALSE
                WHERE resource_id = $1
                """,
                resource_id,
            )
        return result == "UPDATE 1"
