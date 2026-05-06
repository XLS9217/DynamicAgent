"""

act as general interface of the RAG system

"""
import os
from pathlib import Path
from datetime import datetime
from workflow.inbound_v2.knowledge_inbound_workflow import KnowledgeInboundWorkflow
from workflow.retrieve.knowledge_retrieve_workflow import KnowledgeRetrieveWorkflow
from workflow.workflow_base import build_workflow
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.knowledge.knowledge_structs import Bucket


class KnowledgeInterface:

    @classmethod
    def _get_bucket_log_path(cls, bucket_name: str, operation: str) -> Path:
        """
        Get the log path for a bucket operation.

        Args:
            bucket_name: Bucket name
            operation: Operation name (e.g., "inbound", "retrieve")

        Returns:
            Path to the log file with timestamp
        """
        cache_dir = os.getenv("CACHE_DIR", "./cache")
        bucket_log_dir = Path(cache_dir) / "bucket" / bucket_name
        bucket_log_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped log file for each operation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return bucket_log_dir / f"{operation}_{timestamp}.jsonl"

    @classmethod
    async def create_bucket(cls, name: str, description: str = ""):
        """
        Create a new bucket for storing knowledge.

        Args:
            name: Bucket name
            description: Optional bucket description

        Returns:
            Bucket name
        """
        bucket = Bucket(name=name, description=description)
        return await KnowledgeAccessor.create_bucket(bucket)

    @classmethod
    async def check_bucket(cls, name: str):
        """
        Check if a bucket exists.

        Args:
            name: Bucket name

        Returns:
            True if bucket exists, False otherwise
        """
        bucket = await KnowledgeAccessor.get_bucket(name)
        return bucket is not None

    @classmethod
    async def delete_bucket(cls, name: str):
        """
        Delete a bucket and all its contents.

        Args:
            name: Bucket name

        Returns:
            Success message
        """
        await KnowledgeAccessor.delete_bucket(name)
        return f"Bucket {name} deleted successfully"

    @classmethod
    async def inbound(cls, instruction_query: str, knowledge_text: str, bucket_name: str, workflow_log_path=None):
        """
        Inbound entry point after file textification.
        Runs blueprint matching → filling → collision → storage, all scoped to bucket.

        Returns: Success message with entity count
        """
        # Use bucket-specific log path if not provided
        if workflow_log_path is None:
            workflow_log_path = cls._get_bucket_log_path(bucket_name, "inbound")

        inbound_wf = await build_workflow(
            KnowledgeInboundWorkflow,
            knowledge_text,
            instruction_query,
            bucket_name,
            knowledge_accessor=KnowledgeAccessor,
            workflow_log_path=workflow_log_path
        )
        results = await inbound_wf.execute()
        return f"Processed {len(results)} entities successfully"

    @classmethod
    async def retrieve(cls, query: str, bucket_name: str, top_k: int = 10, score_threshold: float = 0.3):
        """
        Retrieve entry point for searching knowledge.
        Returns reconstructed blueprint instances matching the query.

        Args:
            query: Natural language search query
            bucket_name: Bucket to search in
            top_k: Number of knowledge nodes to retrieve
            score_threshold: Minimum avg distance score (0-1, higher=more relevant). Default 0.3

        Returns:
            List of reconstructed instances with filled attributes
        """
        retrieve_wf = await build_workflow(
            KnowledgeRetrieveWorkflow,
            query,
            bucket_name,
            top_k,
            score_threshold,
            knowledge_accessor=KnowledgeAccessor
        )
        return await retrieve_wf.execute()
