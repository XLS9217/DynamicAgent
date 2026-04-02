"""

act as general interface of the RAG system

"""
from workflow.inbound.knowledge_inbound_workflow import KnowledgeInboundWorkflow
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
    def retrieve(cls, query, bucket_name):
        pass
