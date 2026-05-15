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
            schema.add_field("kn_id", DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field("instance_id", DataType.VARCHAR, max_length=64)
            schema.add_field("attribute_id", DataType.VARCHAR, max_length=64)
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
                    WHERE blueprint_id IN (
                        SELECT blueprint_id FROM blueprint WHERE bucket_name = $1
                    )
                """, bucket_name)
                await conn.execute("""
                    DELETE FROM blueprint_attribute
                    WHERE blueprint_id IN (
                        SELECT blueprint_id FROM blueprint WHERE bucket_name = $1
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
                "INSERT INTO blueprint (blueprint_id, bucket_name, name, description) VALUES ($1, $2, $3, $4)",
                bp_id, blueprint.bucket_name, blueprint.name, blueprint.description,
            )
            for attr_name, attr_schema in blueprint.attributes.items():
                attr_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO blueprint_attribute (attribute_id, blueprint_id, name, description, is_identifier) VALUES ($1, $2, $3, $4, $5)",
                    attr_id, bp_id, attr_name, attr_schema.description, attr_schema.is_identifier,
                )
        return bp_id

    @staticmethod
    async def get_blueprint(blueprint_id: str) -> Blueprint | None:
        """Get a blueprint by ID."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT bucket_name, name, description FROM blueprint WHERE blueprint_id = $1", blueprint_id)
            if row is None:
                return None
            attrs = await conn.fetch("SELECT name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", blueprint_id)
            return Blueprint(
                blueprint_id=blueprint_id,
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
            rows = await conn.fetch("SELECT blueprint_id, bucket_name, name, description FROM blueprint WHERE bucket_name = $1", bucket_name)
            results = []
            for row in rows:
                attrs = await conn.fetch("SELECT name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", row["blueprint_id"])
                results.append(Blueprint(
                    blueprint_id=row["blueprint_id"],
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
            rows = await conn.fetch("SELECT attribute_id, blueprint_id, name, description, is_identifier FROM blueprint_attribute WHERE blueprint_id = $1", blueprint_id)
            return [BlueprintAttribute(**dict(r)) for r in rows]

    @staticmethod
    async def create_instance(instance_id: str, blueprint_id: str):
        """Create a blueprint_instance row mapping instance_id to blueprint_id."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO blueprint_instance (instance_id, blueprint_id) VALUES ($1, $2)",
                instance_id, blueprint_id,
            )

    @staticmethod
    async def get_instances_by_blueprint(blueprint_id: str) -> list[str]:
        """Get all instance_ids for a blueprint."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT instance_id FROM blueprint_instance WHERE blueprint_id = $1 ORDER BY instance_id",
                blueprint_id,
            )
            return [r["instance_id"] for r in rows]

    @classmethod
    async def get_filled_instances_by_blueprint(cls, blueprint_id: str) -> list[dict]:
        """
        Get all filled instances for a blueprint with their attribute values.
        Returns: list of {"instance_id": str, attr_name: value, ...}
        """
        # Step 1: get blueprint (for bucket_name + attribute_id -> name map)
        blueprint = await cls.get_blueprint(blueprint_id)
        if blueprint is None:
            return []
        attrs = await cls.get_attributes(blueprint_id)
        attr_id_to_name = {a.attribute_id: a.name for a in attrs}

        # Step 2: get all instance_ids for this blueprint
        instance_ids = await cls.get_instances_by_blueprint(blueprint_id)
        if not instance_ids:
            return []

        # Step 3: query Milvus for all nodes belonging to these instances
        collection_name = _collection_name(blueprint.bucket_name)
        client = MilvusInstance.get_client()
        id_list = ", ".join(f'"{iid}"' for iid in instance_ids)
        nodes = client.query(
            collection_name=collection_name,
            filter=f"instance_id in [{id_list}]",
            output_fields=["instance_id", "attribute_id", "value"],
        )

        # Step 4: assemble {instance_id: {attr_name: value, ...}}
        instances = {iid: {"instance_id": iid} for iid in instance_ids}
        for n in nodes:
            iid = n["instance_id"]
            attr_name = attr_id_to_name.get(n["attribute_id"])
            if attr_name and iid in instances:
                instances[iid][attr_name] = n["value"]
        return list(instances.values())

    @staticmethod
    async def get_all_instances(bucket_name: str) -> list[BlueprintInstance]:
        """Get all instances in a bucket as (instance_id, blueprint_id) pairs."""
        pool = PgInstance.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT bi.instance_id, bi.blueprint_id
                FROM blueprint_instance bi
                JOIN blueprint b ON bi.blueprint_id = b.blueprint_id
                WHERE b.bucket_name = $1
                ORDER BY bi.instance_id
            """, bucket_name)
            return [BlueprintInstance(**dict(r)) for r in rows]

    # =====================================
    # Knowledge node related
    # =====================================

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
                output_fields=["kn_id", "instance_id", "value"],
            )
        else:
            return MilvusInstance.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                top_k=top_k,
                output_fields=["kn_id", "instance_id", "value"],
            )

    @staticmethod
    def get_by_ids(bucket_name: str, ids: list[str]) -> list[dict]:
        """Get knowledge nodes by IDs."""
        collection_name = _collection_name(bucket_name)
        client = MilvusInstance.get_client()
        return client.get(
            collection_name=collection_name,
            ids=ids,
            output_fields=["kn_id", "instance_id", "value"],
        )

    @staticmethod
    def delete_by_ids(bucket_name: str, ids: list[str]):
        """Delete knowledge nodes by IDs."""
        collection_name = _collection_name(bucket_name)
        MilvusInstance.delete(collection_name, ids)
