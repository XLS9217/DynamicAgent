import os
from typing import Optional, List, Dict, Any
from pymilvus import MilvusClient
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class MilvusInstance:
    _client: Optional[MilvusClient] = None

    @staticmethod
    def normalize_model_name(model_name: str) -> str:
        normalized = model_name.replace("/", "_").replace("-", "_").replace(".", "")
        return normalized.upper()

    @classmethod
    def initialize(cls) -> None:
        if cls._client is None:
            milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
            cls._client = MilvusClient(uri=milvus_uri)
            logger.info(f"Milvus client initialized with URI: {milvus_uri}")

    @classmethod
    def get_client(cls) -> MilvusClient:
        if cls._client is None:
            cls.initialize()
        return cls._client

    @classmethod
    def search(
        cls,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        output_fields: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        client = cls.get_client()
        results = client.search(
            collection_name=collection_name,
            data=[query_vector],
            limit=top_k,
            output_fields=output_fields,
            filter=filter_expr,
        )
        flat = results[0] if results else []
        logger.info(f"Retrieved {len(flat)} results from collection '{collection_name}'")
        return flat

    @classmethod
    def delete(
        cls,
        collection_name: str,
        ids: List[Any],
    ) -> None:
        client = cls.get_client()
        client.delete(collection_name=collection_name, ids=ids)
        logger.info(f"Deleted {len(ids)} entities from collection '{collection_name}'")

    @classmethod
    def upsert(
        cls,
        collection_name: str,
        data: List[Dict[str, Any]],
    ) -> None:
        client = cls.get_client()
        client.upsert(collection_name=collection_name, data=data)
        logger.info(f"Upserted {len(data)} entities into collection '{collection_name}'")

    @classmethod
    def create_collection(
        cls,
        collection_name: str,
        dimension: int,
    ) -> str:
        client = cls.get_client()
        if client.has_collection(collection_name):
            logger.info(f"Collection '{collection_name}' already exists")
            return collection_name
        client.create_collection(
            collection_name=collection_name,
            dimension=dimension,
        )
        logger.info(f"Created collection '{collection_name}' with dimension {dimension}")
        return collection_name

    @classmethod
    def get_collection_info(cls, collection_name: str) -> Optional[Dict[str, Any]]:
        client = cls.get_client()
        info = client.describe_collection(collection_name=collection_name)
        logger.info(f"Retrieved collection info for '{collection_name}'")
        return info

    @classmethod
    def close(cls) -> None:
        if cls._client is not None:
            cls._client.close()
            cls._client = None
            logger.info("Milvus client closed")
