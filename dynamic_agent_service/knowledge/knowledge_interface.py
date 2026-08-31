"""General interface for knowledge retrieval."""

from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.knowledge.knowledge_retrieve import KnowledgeRetriever
from dynamic_agent_service.knowledge.knowledge_structs import Bucket


class KnowledgeInterface:
    @classmethod
    async def create_bucket(cls, name: str, description: str = ""):
        bucket = Bucket(name=name, description=description)
        return await KnowledgeAccessor.create_bucket(bucket)

    @classmethod
    async def check_bucket(cls, name: str):
        bucket = await KnowledgeAccessor.get_bucket(name)
        return bucket is not None

    @classmethod
    async def delete_bucket(cls, name: str):
        await KnowledgeAccessor.delete_bucket(name)
        return f"Bucket {name} deleted successfully"

    @classmethod
    async def retrieve(
        cls,
        query: str,
        bucket_name: str,
        top_k: int = 10,
        score_threshold: float = 0.3,
    ):
        """Search knowledge and return reconstructed blueprint instances."""
        retriever = KnowledgeRetriever()
        await retriever.build(
            query,
            bucket_name,
            top_k,
            score_threshold,
        )
        return await retriever.execute()

    @classmethod
    async def expand_node_ids(cls, bucket_name: str, node_ids: list[str]):
        """Expand stored knowledge-node IDs into their values."""
        if not node_ids:
            return []
        return KnowledgeAccessor.get_by_ids(bucket_name, node_ids)
