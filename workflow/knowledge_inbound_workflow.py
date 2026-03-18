from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.vision_engine import VisionEngine
from workflow.blueprint_filling_workflow import BlueprintFillingWorkflow
from workflow.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.file_textification_workflow import FileTextificationWorkflow
from workflow.workflow_base import WorkflowBase


class KnowledgeInboundWorkflow(WorkflowBase):
    def __init__(
        self,
        language_engine: LanguageEngine,
        vision_engine: VisionEngine,
        file_source: str | bytes,
        filetype: str,
        inbound_query: str
    ):
        super().__init__()
        self.language_engine = language_engine
        self.vision_engine = vision_engine
        self.file_source = file_source
        self.filetype = filetype
        self.inbound_query = inbound_query
        self._raw_knowledge_text = ""
        self._blueprint_schema = None
        self._filled_blueprint = {}

    async def execute(self) -> dict:
        self._append_log("Knowledge inbound started")
        self._raw_knowledge_text = await self.execute_subflow(
            FileTextificationWorkflow,
            self.vision_engine,
            self.file_source,
            self.filetype
        )
        self._append_log(f"Extracted {len(self._raw_knowledge_text)} characters")

        self._blueprint_schema = await self.execute_subflow(
            BlueprintGenerationWorkflow,
            self.language_engine,
            self.inbound_query
        )
        self._append_log(f"Generated {len(self._blueprint_schema.attributes)} blueprint attributes")

        self._filled_blueprint = await self.execute_subflow(
            BlueprintFillingWorkflow,
            self.language_engine,
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
