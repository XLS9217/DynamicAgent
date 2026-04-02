"""
Knowledge node accessor for Milvus.

Schema: bucket_{bucket_name} (one collection per bucket)
├── id              (VARCHAR, primary key) — blueprint_instance.id from PG
├── instance_id     (VARCHAR)              — groups entities from same ingestion
├── value           (VARCHAR)              — the raw attribute text chunk
├── embedding       (FLOAT_VECTOR)         — dense vector of value only
"""
from pymilvus import DataType
from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance


def _collection_name(bucket_name: str) -> str:
    return f"bucket_{bucket_name.replace('-', '_')}"


class KnowledgeNodeAccessor(DataAccessor):

    @classmethod
    async def ensure_tables_exist(cls, bucket_name: str) -> bool:
        collection_name = _collection_name(bucket_name)
        dimension = KnowledgeEngine.get_dimension()
        client = MilvusInstance.get_client()
        if client.has_collection(collection_name):
            return True

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("instance_id", DataType.VARCHAR, max_length=64)
        schema.add_field("value", DataType.VARCHAR, max_length=65535)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

        client.create_collection(collection_name, schema=schema)

        index_params = client.prepare_index_params()
        index_params.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_index(collection_name, index_params)

        client.load_collection(collection_name)
        return True

    @staticmethod
    def upsert_entities(bucket_name: str, entities: list[dict]):
        """
        Each entity dict: {"id": str, "instance_id": str, "value": str, "embedding": list[float]}
        """
        collection_name = _collection_name(bucket_name)
        collection_name = _collection_name(bucket_name)
        MilvusInstance.upsert(collection_name, entities)

    @staticmethod
    def search(
        bucket_name: str,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[dict]:
        collection_name = _collection_name(bucket_name)
        return MilvusInstance.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            top_k=top_k,
            output_fields=["instance_id", "value"],
        )

    @staticmethod
    def get_by_ids(bucket_name: str, ids: list[str]) -> list[dict]:
        collection_name = _collection_name(bucket_name)
        client = MilvusInstance.get_client()
        return client.get(
            collection_name=collection_name,
            ids=ids,
            output_fields=["instance_id", "value"],
        )

    @staticmethod
    def delete_by_ids(bucket_name: str, ids: list[str]):
        collection_name = _collection_name(bucket_name)
        MilvusInstance.delete(collection_name, ids)