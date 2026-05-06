"""
End-to-end workflow for ingesting knowledge text into the knowledge base (v2).

Orchestrates the inbound pipeline:
1. Use InboundTaskWorkflow to locate entity types and find/create blueprints
2. Process tasks in parallel via asyncio.gather
3. For each task: extract ALL matching instances from knowledge text and persist each via PersistInstanceWorkflow
"""

import asyncio
from workflow.inbound_v2.inbound_task_workflow import InboundTaskWorkflow
from workflow.inbound_v2.blueprint_multi_filling_workflow import BlueprintMultiFillingWorkflow
from workflow.inbound_v2.persist_instance_workflow import PersistInstanceWorkflow
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
        """Process a single task: extract all matching instances and persist each"""
        blueprint = task["blueprint"]
        enriched_query = task["enriched_query"]

        self.append_log(f"Processing task: {enriched_query}")

        # Extract all matching instances from knowledge text
        identifier_name = next(k for k, v in blueprint.attributes.items() if v.is_identifier)
        instances = await self.execute_subflow(
            BlueprintMultiFillingWorkflow,
            blueprint.name,
            blueprint.description,
            {k: v.description for k, v in blueprint.attributes.items()},
            self.knowledge_text,
            identifier_name,
            enriched_query
        )
        self.append_log(f"Extracted {len(instances)} instances for {blueprint.name}")

        # Persist each instance
        persist_results = []
        if self.knowledge_accessor and blueprint.id:
            for instance in instances:
                persist_result = await self.execute_subflow(
                    PersistInstanceWorkflow,
                    blueprint,
                    instance,
                    self.bucket_name,
                    self.knowledge_accessor
                )
                persist_results.append(persist_result)

        return {
            "query": enriched_query,
            "blueprint": blueprint.model_dump(),
            "instances_count": len(instances),
            "persist_results": persist_results
        }