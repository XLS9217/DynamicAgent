"""

act as general interface of the RAG system

"""
from workflow.inbound.knowledge_inbound_workflow import KnowledgeInboundWorkflow
from workflow.retrieve.knowledge_retrieve_workflow import KnowledgeRetrieveWorkflow
from workflow.workflow_base import build_workflow
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor


class KnowledgeInterface:

    @classmethod
    async def inbound(cls, instruction_query: str, knowledge_text: str, bucket_name: str):
        """
        Inbound entry point after file textification.
        Runs blueprint matching → filling → collision → storage, all scoped to bucket.
        """
        inbound_wf = await build_workflow(
            KnowledgeInboundWorkflow,
            knowledge_text,
            instruction_query,
            bucket_name,
            knowledge_accessor=BlueprintAccessor
        )
        return await inbound_wf.execute()

    @classmethod
    async def retrieve(cls, query: str, bucket_name: str, top_k: int = 10):
        """
        Retrieve entry point for searching knowledge.
        Returns reconstructed blueprint instances matching the query.

        Args:
            query: Natural language search query
            bucket_name: Bucket to search in
            top_k: Number of knowledge nodes to retrieve

        Returns:
            List of reconstructed instances with filled attributes
        """
        retrieve_wf = await build_workflow(
            KnowledgeRetrieveWorkflow,
            query,
            bucket_name,
            top_k,
            knowledge_accessor=BlueprintAccessor
        )
        return await retrieve_wf.execute()
