"""
Knowledge node accessor for Milvus.

Schema: entity
├── id              (VARCHAR, primary key) — blueprint_instance.id from PG
├── instance_id     (VARCHAR)              — groups entities from same ingestion
├── value           (VARCHAR)              — the raw attribute text chunk
├── embedding       (FLOAT_VECTOR)         — dense vector of value only
"""
from dynamic_agent_service.data.data_accessor import DataAccessor
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance

COLLECTION_NAME = "entity"


class KnowledgeNodeAccessor(DataAccessor):

    dimension: int = 1536

    @classmethod
    async def ensure_tables_exist(cls) -> bool:
        MilvusInstance.create_collection(COLLECTION_NAME, cls.dimension)
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