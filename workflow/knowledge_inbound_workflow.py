from workflow.blueprint_filling_workflow import BlueprintFillingWorkflow
from workflow.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.blueprint_matching_workflow import BlueprintMatchingWorkflow
from workflow.file_textification_workflow import FileTextificationWorkflow
from workflow.workflow_base import WorkflowBase

import uuid


class KnowledgeInboundWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.file_source = None
        self.filetype = None
        self.inbound_query = ""
        self.knowledge_accessor = None
        self._raw_knowledge_text = ""
        self._blueprint_schema = None
        self._blueprint_id = None
        self._filled_blueprint = {}

    async def build(self, file_source: str | bytes, filetype: str, inbound_query: str, knowledge_accessor=None):
        self.file_source = file_source
        self.filetype = filetype
        self.inbound_query = inbound_query
        self.knowledge_accessor = knowledge_accessor
        return self

    async def execute(self) -> dict:
        self.append_log("Knowledge inbound started")
        self._raw_knowledge_text = await self.execute_subflow(
            FileTextificationWorkflow,
            self.file_source,
            self.filetype
        )
        self.append_log(f"Extracted {len(self._raw_knowledge_text)} characters")

        if self.knowledge_accessor:
            self._blueprint_schema = await self.execute_subflow(
                BlueprintMatchingWorkflow,
                self.inbound_query,
                self.knowledge_accessor
            )

        if self._blueprint_schema is None:
            self.append_log("No matching blueprint found, generating new one")
            self._blueprint_schema = await self.execute_subflow(
                BlueprintGenerationWorkflow,
                self.inbound_query
            )
            if self.knowledge_accessor:
                self._blueprint_id = await self.knowledge_accessor.create_blueprint(self._blueprint_schema)
                self.append_log(f"Saved new blueprint: {self._blueprint_schema.name} ({self._blueprint_id})")

        self.append_log(f"Using blueprint: {self._blueprint_schema.name} with {len(self._blueprint_schema.attributes)} attributes")

        self._filled_blueprint = await self.execute_subflow(
            BlueprintFillingWorkflow,
            {k: v.description for k, v in self._blueprint_schema.attributes.items()},
            self._raw_knowledge_text
        )
        self.append_log(f"Filled {len(self._filled_blueprint)} blueprint attributes")

        if self.knowledge_accessor and self._blueprint_id:
            await self._persist_instance()

        self.append_log("Knowledge inbound completed")

        return {
            "query": self.inbound_query,
            "blueprint": self._blueprint_schema.model_dump(),
            "attribute_values": self._filled_blueprint
        }

    async def _persist_instance(self):
        attrs = await self.knowledge_accessor.get_attributes(self._blueprint_id)
        attr_name_to_id = {a.name: a.id for a in attrs}

        filled_attr_ids = [
            attr_name_to_id[name]
            for name in self._filled_blueprint
            if name in attr_name_to_id
        ]

        instance_id = str(uuid.uuid4())
        await self.knowledge_accessor.create_instance(instance_id, filled_attr_ids)
        self.append_log(f"Persisted instance {instance_id} with {len(filled_attr_ids)} attributes")
        # TODO: upsert entities to Milvus with embeddings via KnowledgeNodeAccessor