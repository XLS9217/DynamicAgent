import os
from typing import Optional, List, Dict, Any
from pymilvus import (
    MilvusClient, AnnSearchRequest, WeightedRanker, DataType, Function, FunctionType,
)
from dynamic_agent_service.logging.setup_logging import get_my_logger

logger = get_my_logger("storage")


class MilvusInstance:
    _client: Optional[MilvusClient] = None

    @staticmethod
    def normalize_model_name(model_name: str) -> str:
        normalized = model_name.replace("/", "_").replace("-", "_").replace(".", "")
        return normalized.upper()

    @classmethod
    def initialize(cls) -> None:
        if cls._client is None:
            milvus_uri = os.getenv("MILVUS_URI")
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
        vector_field: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        client = cls.get_client()
        search_options = {"anns_field": vector_field} if vector_field else {}
        results = client.search(
            collection_name=collection_name,
            data=[query_vector],
            limit=top_k,
            output_fields=output_fields,
            filter=filter_expr or "",
            **search_options,
        )
        flat = results[0] if results else []
        logger.info(f"Retrieved {len(flat)} results from collection '{collection_name}'")
        return flat

    @classmethod
    def hybrid_search(
        cls,
        collection_name: str,
        query_vector: List[float],
        query_text: str,
        top_k: int = 10,
        embedding_weight: float = 0.5,
        bm25_weight: float = 0.5,
        output_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining dense vector (ANN) and sparse retrieval (BM25).

        Uses WeightedRanker with the schema from create_hybrid_collection().
        Returned IDs use kn_id for compatibility with existing vector callers.
        """
        client = cls.get_client()
        output_fields = output_fields or []

        # Dense vector search request
        dense_req = AnnSearchRequest(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE"},
            limit=top_k * 2
        )

        # BM25 sparse search request (pass text directly, Milvus converts to sparse vector)
        sparse_req = AnnSearchRequest(
            data=[query_text],
            anns_field="sparse_vector",
            param={"metric_type": "BM25"},
            limit=top_k * 2
        )

        # Native hybrid search with WeightedRanker
        # Weights order matches reqs order: [dense_weight, sparse_weight]
        results = client.hybrid_search(
            collection_name=collection_name,
            reqs=[dense_req, sparse_req],
            ranker=WeightedRanker(embedding_weight, bm25_weight),
            limit=top_k,
            output_fields=output_fields
        )

        # Flatten results structure
        flat_results = []
        for hit in results[0] if results else []:
            item = {'kn_id': hit['id'], 'distance': hit['distance']}
            entity = hit.get('entity', {})
            for field in output_fields:
                if field in entity:
                    item[field] = entity[field]
            flat_results.append(item)

        logger.info(f"Hybrid search retrieved {len(flat_results)} results from collection '{collection_name}'")
        return flat_results

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
    def create_hybrid_collection(cls, collection_name: str, dimension: int) -> str:
        """Create a standalone text/vector collection with dense and BM25 indexes.

        Upsert kn_id (string), value (text), and embedding (float vector).
        Milvus generates sparse_vector. No relational metadata is required.
        Existing collections are left unchanged and must have a compatible schema.
        """
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        client = cls.get_client()
        if client.has_collection(collection_name):
            return collection_name

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("kn_id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("value", DataType.VARCHAR, max_length=65535, enable_analyzer=True)
        schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_function(Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["value"],
            output_field_names=["sparse_vector"],
        ))
        indexes = client.prepare_index_params()
        indexes.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
        indexes.add_index("sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        client.create_collection(
            collection_name=collection_name, schema=schema, index_params=indexes,
        )
        client.load_collection(collection_name)
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
