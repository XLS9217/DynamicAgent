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

    @staticmethod
    async def delete_bucket(bucket_name: str):
        """
        Delete a bucket and all associated data:
        1. Delete from PostgreSQL in transaction (ACID)
        2. Drop Milvus collection only after PG commit succeeds
        """
        from dynamic_agent_service.external_service.milvus_instance import MilvusInstance

        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Delete blueprint_instance rows
                await conn.execute("""
                    DELETE FROM blueprint_instance
                    WHERE attribute_id IN (
                        SELECT ba.id FROM blueprint_attribute ba
                        JOIN blueprint b ON ba.blueprint_id = b.id
                        WHERE b.bucket_name = $1
                    )
                """, bucket_name)

                # Delete blueprint_attribute rows
                await conn.execute("""
                    DELETE FROM blueprint_attribute
                    WHERE blueprint_id IN (
                        SELECT id FROM blueprint WHERE bucket_name = $1
                    )
                """, bucket_name)

                # Delete blueprint rows
                await conn.execute("DELETE FROM blueprint WHERE bucket_name = $1", bucket_name)

                # Delete bucket row
                await conn.execute("DELETE FROM bucket WHERE name = $1", bucket_name)

        # Only drop Milvus collection after PG transaction commits successfully
        collection_name = f"bucket_{bucket_name.replace('-', '_')}"
        client = MilvusInstance.get_client()
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)