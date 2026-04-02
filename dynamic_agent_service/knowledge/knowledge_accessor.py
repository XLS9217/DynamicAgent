"""
Bucket accessor for PostgreSQL.

Table:
  bucket (name, description)
"""
from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.knowledge_structs import Bucket


class KnowledgeAccessor(DataAccessor):

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bucket (
                    name        TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT ''
                );
            """)
        return True

    @staticmethod
    async def create_bucket(bucket: Bucket) -> str:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO bucket (name, description) VALUES ($1, $2)",
                bucket.name, bucket.description,
            )
        return bucket.name

    @staticmethod
    async def get_bucket(bucket_name: str) -> Bucket | None:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT name, description FROM bucket WHERE name = $1", bucket_name)
            if row is None:
                return None
            return Bucket(**dict(row))

    @staticmethod
    async def get_bucket_list() -> list[Bucket]:
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, description FROM bucket")
            return [Bucket(**dict(r)) for r in rows]