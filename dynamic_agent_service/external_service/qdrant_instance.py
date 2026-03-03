import os
from typing import Optional, List, Dict, Any
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    SearchRequest,
)
from src.util.setup_logging import get_my_logger

logger = get_my_logger()


class QdrantInstance:
    _client: Optional[AsyncQdrantClient] = None

    @staticmethod
    def normalize_model_name(model_name: str) -> str:
        """
        Normalize embedding model name to valid Qdrant collection name.

        Example: "Qwen/Qwen3-Embedding-0.6B" -> "QWEN_QWEN3_EMBEDDING_06B"

        :param model_name: Original model name
        :return: Normalized collection name
        """
        normalized = model_name.replace("/", "_").replace("-", "_").replace(".", "")
        return normalized.upper()

    @classmethod
    async def initialize(cls) -> None:
        """Initialize Qdrant connection"""
        if cls._client is None:
            qdrant_host = os.getenv("QDRANT_HOST")
            qdrant_rest_port = int(os.getenv("QDRANT_REST_PORT"))
            qdrant_grpc_port = int(os.getenv("QDRANT_GRPC_PORT"))
            qdrant_api_key = os.getenv("QDRANT_API_KEY")

            try:
                cls._client = AsyncQdrantClient(
                    host=qdrant_host,
                    port=qdrant_rest_port,
                    grpc_port=qdrant_grpc_port,
                    prefer_grpc=True,
                    api_key=qdrant_api_key,
                    timeout=10,
                    check_compatibility=False
                )
                logger.info(f"Qdrant client initialized with host: {qdrant_host}:{qdrant_rest_port} (gRPC: {qdrant_grpc_port})")
            except Exception as e:
                logger.error(f"Failed to initialize Qdrant client: {e}")
                raise

    @classmethod
    async def get_client(cls) -> AsyncQdrantClient:
        """Get Qdrant client instance"""
        if cls._client is None:
            await cls.initialize()
        return cls._client

    @classmethod
    async def get_points(
        cls,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        query_filter: Optional[Filter] = None,
        score_threshold: Optional[float] = None,
        with_payload: bool = True,
        with_vectors: bool = False
    ) -> List[Any]:
        """Search for similar points in a collection"""
        try:
            client = await cls.get_client()
            response = await client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=top_k,
                query_filter=query_filter,
                score_threshold=score_threshold,
                with_payload=with_payload,
                with_vectors=with_vectors
            )
            results = response.points if hasattr(response, 'points') else []
            logger.info(f"Retrieved {len(results)} points from collection '{collection_name}'")
            return results
        except Exception as e:
            logger.error(f"Failed to get points from collection '{collection_name}': {e}")
            return []

    @classmethod
    async def delete_points(
            cls,
            collection_name: str,
            ids: List[str],
            wait: bool = True
    ) -> bool:
        """Delete points from a collection"""
        try:
            client = await cls.get_client()
            await client.delete(
                collection_name=collection_name,
                points_selector=ids,
                wait=wait
            )
            logger.info(f"Deleted {len(ids)} points from collection '{collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to delete points from collection '{collection_name}': {e}")
            return False

    @classmethod
    async def upsert_points(
        cls,
        collection_name: str,
        points: List[PointStruct],
        wait: bool = True
    ) -> None:
        """Upsert points into a collection"""
        try:
            client = await cls.get_client()
            await client.upsert(
                collection_name=collection_name,
                points=points,
                wait=wait
            )
            logger.info(f"Upserted {len(points)} points into collection '{collection_name}'")
        except Exception as e:
            logger.error(f"Failed to upsert points into collection '{collection_name}': {e}")
            raise

    @classmethod
    async def get_collection_info(cls, collection_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a collection"""
        try:
            client = await cls.get_client()
            info = await client.get_collection(collection_name=collection_name)
            logger.info(f"Retrieved collection info for '{collection_name}'")
            return info
        except Exception as e:
            logger.error(f"Failed to get collection info for '{collection_name}': {e}")
            return None

    @classmethod
    async def create_collection(
        cls,
        collection_name: str,
        vector_size: int,
        distance: Distance = Distance.COSINE
    ) -> str:
        """Create a new collection"""
        try:
            client = await cls.get_client()

            # Check if collection already exists
            collections = await client.get_collections()
            existing_names = [col.name for col in collections.collections]

            if collection_name in existing_names:
                logger.info(f"Collection '{collection_name}' already exists")
                return collection_name

            # Create new collection
            # Note: Qdrant accepts both integer and string/UUID IDs without explicit configuration
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=distance
                )
            )
            logger.info(f"Created collection '{collection_name}' with vector size {vector_size}")
            return collection_name
        except Exception as e:
            logger.error(f"Failed to create collection '{collection_name}': {e}")
            raise

    @classmethod
    async def close(cls) -> None:
        """Close Qdrant connection"""
        if cls._client is not None:
            await cls._client.close()
            cls._client = None
            logger.info("Qdrant client closed")