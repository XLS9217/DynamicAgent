"""
Blueprint accessor for PostgreSQL.

Tables:
  blueprint            (id, name, description)
  blueprint_attribute  (id, blueprint_id, name, description)
  blueprint_instance   (id, instance_id, attribute_id)
"""
import uuid

from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.knowledge_structs import (
    Blueprint, BlueprintAttribute, BlueprintAttributeSchema, BlueprintInstance,
)


class BlueprintAccessor(DataAccessor):

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS blueprint (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS blueprint_attribute (
                    id           TEXT PRIMARY KEY,
                    blueprint_id TEXT NOT NULL REFERENCES blueprint(id),
                    name         TEXT NOT NULL,
                    description  TEXT NOT NULL,
                    is_identifier BOOLEAN NOT NULL DEFAULT FALSE
                );
                CREATE TABLE IF NOT EXISTS blueprint_instance (
                    id           TEXT PRIMARY KEY,
                    instance_id  TEXT NOT NULL,
                    attribute_id TEXT NOT NULL REFERENCES blueprint_attribute(id)
                );
            """)
        return True

    @staticmethod
    async def create_blueprint(blueprint: Blueprint) -> str:
        bp_id = str(uuid.uuid4())
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO blueprint (id, name, description) VALUES ($1, $2, $3)",
                bp_id, blueprint.name, blueprint.description,
            )
            for attr_name, attr_schema in blueprint.attributes.items():
                attr_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO blueprint_attribute (id, blueprint_id, name, description, is_identifier) VALUES ($1, $2, $3, $4, $5)",
                    attr_id, bp_id, attr_name, attr_schema.description, attr_schema.is_identifier,
                )
        return bp_id

    @staticmethod
    async def get_blueprint(blueprint_id: str) -> Blueprint | None:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT name, description FROM blueprint WHERE id = $1", blueprint_id)
            if row is None:
                return None
            attrs = await conn.fetch("SELECT name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", blueprint_id)
            return Blueprint(
                name=row["name"],
                description=row["description"],
                attributes={a["name"]: BlueprintAttributeSchema(description=a["description"], is_identifier=a["is_identifier"]) for a in attrs},
            )

    @staticmethod
    async def get_blueprint_list() -> list[Blueprint]:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, description FROM blueprint")
            results = []
            for row in rows:
                attrs = await conn.fetch("SELECT name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", row["id"])
                results.append(Blueprint(
                    name=row["name"],
                    description=row["description"],
                    attributes={a["name"]: BlueprintAttributeSchema(description=a["description"], is_identifier=a["is_identifier"]) for a in attrs},
                ))
            return results

    @staticmethod
    async def get_attributes(blueprint_id: str) -> list[BlueprintAttribute]:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, blueprint_id, name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", blueprint_id)
            return [BlueprintAttribute(**dict(r)) for r in rows]

    @staticmethod
    async def create_instance(instance_id: str, attribute_ids: list[str]) -> list[str]:
        pool = PgInstance.get_pool()
        ids = []
        async with pool.acquire() as conn:
            for attr_id in attribute_ids:
                row_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO blueprint_instance (id, instance_id, attribute_id) VALUES ($1, $2, $3)",
                    row_id, instance_id, attr_id,
                )
                ids.append(row_id)
        return ids

    @staticmethod
    async def get_instances_by_instance_id(instance_id: str) -> list[BlueprintInstance]:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, instance_id, attribute_id FROM blueprint_instance WHERE instance_id = $1", instance_id)
            return [BlueprintInstance(**dict(r)) for r in rows]