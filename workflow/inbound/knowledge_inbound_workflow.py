"""
End-to-end workflow for ingesting knowledge text into the knowledge base.

Orchestrates the inbound pipeline: (1) use InboundTaskWorkflow to identify entities and create
tasks, (2) process tasks in parallel via asyncio.gather, (3) for each task: fill blueprint
and persist via PersistInstanceWorkflow.
"""

import asyncio
from workflow.inbound.inbound_task_workflow import InboundTaskWorkflow
from workflow.inbound.blueprint_filling_workflow import BlueprintFillingWorkflow
from workflow.inbound.persist_instance_workflow import PersistInstanceWorkflow
from workflow.workflow_base import WorkflowBase


class KnowledgeInboundWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.knowledge_text = ""
        self.inbound_query = ""
        self.bucket_name = ""
        self.knowledge_accessor = None

    async def build(self, knowledge_text: str, inbound_query: str, bucket_name: str, knowledge_accessor=None):
        self.knowledge_text = knowledge_text
        self.inbound_query = inbound_query
        self.bucket_name = bucket_name
        self.knowledge_accessor = knowledge_accessor
        return self

    async def execute(self) -> list[dict]:
        self.append_log("Knowledge inbound started")
        self.append_log(f"Processing {len(self.knowledge_text)} characters")

        tasks = await self.execute_subflow(
            InboundTaskWorkflow,
            self.knowledge_text,
            self.inbound_query,
            self.bucket_name,
            self.knowledge_accessor
        )

        self.append_log(f"Got {len(tasks)} tasks, processing in parallel")

        results = await asyncio.gather(*[
            self._process_task(task)
            for task in tasks
        ])

        self.append_log(f"Knowledge inbound completed: {len(results)} entities processed")
        return list(results)

    async def _process_task(self, task: dict) -> dict:
        """Process a single task: fill blueprint and persist"""
        blueprint = task["blueprint"]
        enriched_query = task["enriched_query"]

        self.append_log(f"Processing task: {enriched_query}")

        # Fill blueprint
        identifier_name = next(k for k, v in blueprint.attributes.items() if v.is_identifier)
        filled_blueprint = await self.execute_subflow(
            BlueprintFillingWorkflow,
            {k: v.description for k, v in blueprint.attributes.items()},
            self.knowledge_text,
            identifier_name,
            enriched_query
        )
        self.append_log(f"Filled {len(filled_blueprint)} attributes for {enriched_query}")

        # Persist
        persist_result = None
        if self.knowledge_accessor and blueprint.id:
            persist_result = await self.execute_subflow(
                PersistInstanceWorkflow,
                blueprint,
                filled_blueprint,
                self.bucket_name,
                self.knowledge_accessor
            )

        return {
            "query": enriched_query,
            "blueprint": blueprint.model_dump(),
            "attribute_values": filled_blueprint,
            "persist_result": persist_result
        }