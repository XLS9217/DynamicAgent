"""
Unified knowledge accessor for PostgreSQL and Milvus operations.

Handles:
- Bucket operations (PostgreSQL)
- Blueprint operations (PostgreSQL)
- Knowledge node operations (Milvus)
"""
import uuid
from pymilvus import DataType, Function, FunctionType

from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.knowledge.knowledge_structs import (
    Bucket, Blueprint, BlueprintAttribute, BlueprintAttributeSchema, BlueprintInstance,
)


def _collection_name(bucket_name: str) -> str:
    return f"bucket_{bucket_name.replace('-', '_')}"


class KnowledgeAccessor(DataAccessor):

    # =====================================
    # Bucket related
    # =====================================

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        """Initialize all PostgreSQL tables for knowledge system."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bucket (
                    name        TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS blueprint (
                    id          TEXT PRIMARY KEY,
                    bucket_name TEXT NOT NULL REFERENCES bucket(name),
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
    async def create_bucket(bucket: Bucket) -> str:
        """Create a new bucket in PostgreSQL and corresponding Milvus collection."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO bucket (name, description) VALUES ($1, $2)",
                bucket.name, bucket.description,
            )

        # Create Milvus collection for this bucket
        collection_name = _collection_name(bucket.name)
        dimension = KnowledgeEngine.get_dimension()
        client = MilvusInstance.get_client()

        if not client.has_collection(collection_name):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field("instance_id", DataType.VARCHAR, max_length=64)
            schema.add_field("value", DataType.VARCHAR, max_length=65535, enable_analyzer=True)
            schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

            bm25_function = Function(
                name="bm25",
                function_type=FunctionType.BM25,
                input_field_names=["value"],
                output_field_names=["sparse_vector"]
            )
            schema.add_function(bm25_function)

            client.create_collection(collection_name, schema=schema)

            index_params = client.prepare_index_params()
            index_params.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
            index_params.add_index("sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
            client.create_index(collection_name, index_params)

            client.load_collection(collection_name)

        return bucket.name

    @staticmethod
    async def get_bucket(bucket_name: str) -> Bucket | None:
        """Get a bucket by name."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT name, description FROM bucket WHERE name = $1", bucket_name)
            if row is None:
                return None
            return Bucket(**dict(row))

    @staticmethod
    async def get_bucket_list() -> list[Bucket]:
        """Get all buckets."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, description FROM bucket")
            return [Bucket(**dict(r)) for r in rows]

    @staticmethod
    async def delete_bucket(bucket_name: str):
        """Delete a bucket and all associated data (PostgreSQL + Milvus)."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    DELETE FROM blueprint_instance
                    WHERE attribute_id IN (
                        SELECT ba.id FROM blueprint_attribute ba
                        JOIN blueprint b ON ba.blueprint_id = b.id
                        WHERE b.bucket_name = $1
                    )
                """, bucket_name)
                await conn.execute("""
                    DELETE FROM blueprint_attribute
                    WHERE blueprint_id IN (
                        SELECT id FROM blueprint WHERE bucket_name = $1
                    )
                """, bucket_name)
                await conn.execute("DELETE FROM blueprint WHERE bucket_name = $1", bucket_name)
                await conn.execute("DELETE FROM bucket WHERE name = $1", bucket_name)

        collection_name = _collection_name(bucket_name)
        client = MilvusInstance.get_client()
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)

    # =====================================
    # Blueprint related
    # =====================================

    @staticmethod
    async def create_blueprint(blueprint: Blueprint) -> str:
        """Create a new blueprint with its attributes."""
        bp_id = str(uuid.uuid4())
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO blueprint (id, bucket_name, name, description) VALUES ($1, $2, $3, $4)",
                bp_id, blueprint.bucket_name, blueprint.name, blueprint.description,
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
        """Get a blueprint by ID."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT bucket_name, name, description FROM blueprint WHERE id = $1", blueprint_id)
            if row is None:
                return None
            attrs = await conn.fetch("SELECT name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", blueprint_id)
            return Blueprint(
                id=blueprint_id,
                bucket_name=row["bucket_name"],
                name=row["name"],
                description=row["description"],
                attributes={a["name"]: BlueprintAttributeSchema(description=a["description"], is_identifier=a["is_identifier"]) for a in attrs},
            )

    @staticmethod
    async def get_blueprint_list(bucket_name: str) -> list[Blueprint]:
        """Get all blueprints in a bucket."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, bucket_name, name, description FROM blueprint WHERE bucket_name = $1", bucket_name)
            results = []
            for row in rows:
                attrs = await conn.fetch("SELECT name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", row["id"])
                results.append(Blueprint(
                    id=row["id"],
                    bucket_name=row["bucket_name"],
                    name=row["name"],
                    description=row["description"],
                    attributes={a["name"]: BlueprintAttributeSchema(description=a["description"], is_identifier=a["is_identifier"]) for a in attrs},
                ))
            return results

    @staticmethod
    async def get_attributes(blueprint_id: str) -> list[BlueprintAttribute]:
        """Get all attributes for a blueprint."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, blueprint_id, name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", blueprint_id)
            return [BlueprintAttribute(**dict(r)) for r in rows]

    @staticmethod
    async def create_instance(instance_id: str, attribute_ids: list[str]) -> list[str]:
        """Create blueprint instance rows."""
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
    async def get_instances_by_blueprint(blueprint_id: str) -> list[dict]:
        """Get all instances for a blueprint."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT bi.id, bi.instance_id, ba.name as attr_name
                FROM blueprint_instance bi
                JOIN blueprint_attribute ba ON bi.attribute_id = ba.id
                WHERE ba.blueprint_id = $1
                ORDER BY bi.instance_id
            """, blueprint_id)
        instances = {}
        for r in rows:
            iid = r["instance_id"]
            if iid not in instances:
                instances[iid] = {"instance_id": iid, "attributes": {}}
            instances[iid]["attributes"][r["attr_name"]] = r["id"]
        return list(instances.values())

    @staticmethod
    async def get_instances_by_instance_id(instance_id: str) -> list[BlueprintInstance]:
        """Get all blueprint instance rows for a given instance_id."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, instance_id, attribute_id FROM blueprint_instance WHERE instance_id = $1", instance_id)
            return [BlueprintInstance(**dict(r)) for r in rows]

    @staticmethod
    async def get_all_instances(bucket_name: str) -> list[dict]:
        """Get all instances in a bucket."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT bi.id, bi.instance_id, bi.attribute_id, ba.name as attr_name, ba.blueprint_id
                FROM blueprint_instance bi
                JOIN blueprint_attribute ba ON bi.attribute_id = ba.id
                JOIN blueprint b ON ba.blueprint_id = b.id
                WHERE b.bucket_name = $1
                ORDER BY bi.instance_id
            """, bucket_name)
        instances = {}
        for r in rows:
            iid = r["instance_id"]
            if iid not in instances:
                instances[iid] = {"instance_id": iid, "blueprint_id": r["blueprint_id"], "attributes": []}
            instances[iid]["attributes"].append({
                "row_id": r["id"],
                "attr_name": r["attr_name"],
            })
        return list(instances.values())

    # =====================================
    # Knowledge node related
    # =====================================

    @classmethod
    async def ensure_knowledge_node_tables_exist(cls, bucket_name: str) -> bool:
        """Ensure Milvus collection exists for a bucket."""
        collection_name = _collection_name(bucket_name)
        dimension = KnowledgeEngine.get_dimension()
        client = MilvusInstance.get_client()
        if client.has_collection(collection_name):
            return True

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("instance_id", DataType.VARCHAR, max_length=64)
        schema.add_field("value", DataType.VARCHAR, max_length=65535, enable_analyzer=True)
        schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

        bm25_function = Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["value"],
            output_field_names=["sparse_vector"]
        )
        schema.add_function(bm25_function)

        client.create_collection(collection_name, schema=schema)

        index_params = client.prepare_index_params()
        index_params.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index("sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        client.create_index(collection_name, index_params)

        client.load_collection(collection_name)
        return True

    @staticmethod
    def upsert_entities(bucket_name: str, entities: list[dict]):
        """Upsert knowledge nodes to Milvus."""
        collection_name = _collection_name(bucket_name)
        MilvusInstance.upsert(collection_name, entities)

    @staticmethod
    def search(
        bucket_name: str,
        query_embedding: list[float],
        query_text: str = "",
        top_k: int = 10,
        embedding_weight: float = 0.5,
        bm25_weight: float = 0.5,
    ) -> list[dict]:
        """Hybrid search combining dense vector and BM25."""
        collection_name = _collection_name(bucket_name)

        if query_text and bm25_weight > 0:
            return MilvusInstance.hybrid_search(
                collection_name=collection_name,
                query_vector=query_embedding,
                query_text=query_text,
                top_k=top_k,
                embedding_weight=embedding_weight,
                bm25_weight=bm25_weight,
                output_fields=["instance_id", "value"],
            )
        else:
            return MilvusInstance.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                top_k=top_k,
                output_fields=["instance_id", "value"],
            )

    @staticmethod
    def get_by_ids(bucket_name: str, ids: list[str]) -> list[dict]:
        """Get knowledge nodes by IDs."""
        collection_name = _collection_name(bucket_name)
        client = MilvusInstance.get_client()
        return client.get(
            collection_name=collection_name,
            ids=ids,
            output_fields=["instance_id", "value"],
        )

    @staticmethod
    def delete_by_ids(bucket_name: str, ids: list[str]):
        """Delete knowledge nodes by IDs."""
        collection_name = _collection_name(bucket_name)
        MilvusInstance.delete(collection_name, ids)
