from workflow.blueprint_filling_workflow import BlueprintFillingWorkflow
from workflow.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.blueprint_matching_workflow import BlueprintMatchingWorkflow
from workflow.file_textification_workflow import FileTextificationWorkflow
from workflow.workflow_base import WorkflowBase


class KnowledgeInboundWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.file_source = None
        self.filetype = None
        self.inbound_query = ""
        self.knowledge_accessor = None
        self._raw_knowledge_text = ""
        self._blueprint_schema = None
        self._filled_blueprint = {}

    async def build(self, file_source: str | bytes, filetype: str, inbound_query: str, knowledge_accessor=None):
        self.file_source = file_source
        self.filetype = filetype
        self.inbound_query = inbound_query
        self.knowledge_accessor = knowledge_accessor
        return self

    async def execute(self) -> dict:
        self._append_log("Knowledge inbound started")
        self._raw_knowledge_text = await self.execute_subflow(
            FileTextificationWorkflow,
            self.file_source,
            self.filetype
        )
        self._append_log(f"Extracted {len(self._raw_knowledge_text)} characters")

        if self.knowledge_accessor:
            self._blueprint_schema = await self.execute_subflow(
                BlueprintMatchingWorkflow,
                self.inbound_query,
                self.knowledge_accessor
            )

        if self._blueprint_schema is None:
            self._append_log("No matching blueprint found, generating new one")
            self._blueprint_schema = await self.execute_subflow(
                BlueprintGenerationWorkflow,
                self.inbound_query
            )
            if self.knowledge_accessor:
                self.knowledge_accessor.create_blueprint(self._blueprint_schema)
                self._append_log(f"Saved new blueprint: {self._blueprint_schema.name}")

        self._append_log(f"Using blueprint: {self._blueprint_schema.name} with {len(self._blueprint_schema.attributes)} attributes")

        self._filled_blueprint = await self.execute_subflow(
            BlueprintFillingWorkflow,
            self._blueprint_schema.attributes,
            self._raw_knowledge_text
        )
        self._append_log(f"Filled {len(self._filled_blueprint)} blueprint attributes")
        self._append_log("Knowledge inbound completed")

        return {
            "query": self.inbound_query,
            "blueprint": self._blueprint_schema.model_dump(),
            "attribute_values": self._filled_blueprint
        }