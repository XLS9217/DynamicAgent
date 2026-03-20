"""
Knowledge node accessor for Milvus.

Schema: entity
├── id              (VARCHAR, primary key) — blueprint_instance.id from PG
├── instance_id     (VARCHAR)              — groups entities from same ingestion
├── value           (VARCHAR)              — the raw attribute text chunk
├── embedding       (FLOAT_VECTOR)         — dense vector of value only
"""
from pymilvus import DataType
from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance

COLLECTION_NAME = "entity"


class KnowledgeNodeAccessor(DataAccessor):

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        dimension = KnowledgeEngine.get_dimension()
        client = MilvusInstance.get_client()
        if client.has_collection(COLLECTION_NAME):
            return True

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("instance_id", DataType.VARCHAR, max_length=64)
        schema.add_field("value", DataType.VARCHAR, max_length=65535)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

        client.create_collection(COLLECTION_NAME, schema=schema)

        index_params = client.prepare_index_params()
        index_params.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_index(COLLECTION_NAME, index_params)

        client.load_collection(COLLECTION_NAME)
        return True

    @staticmethod
    def upsert_entities(
        entities: list[dict],
    ):
        """
        Each entity dict: {"id": str, "instance_id": str, "value": str, "embedding": list[float]}
        """
        MilvusInstance.upsert(COLLECTION_NAME, entities)

    @staticmethod
    def search(
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[dict]:
        return MilvusInstance.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            top_k=top_k,
            output_fields=["instance_id", "value"],
        )

    @staticmethod
    def get_by_ids(ids: list[str]) -> list[dict]:
        client = MilvusInstance.get_client()
        return client.get(
            collection_name=COLLECTION_NAME,
            ids=ids,
            output_fields=["instance_id", "value"],
        )

    @staticmethod
    def delete_by_ids(ids: list[str]):
        MilvusInstance.delete(COLLECTION_NAME, ids)