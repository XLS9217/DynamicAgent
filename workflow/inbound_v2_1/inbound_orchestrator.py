"""
Orchestrate the full knowledge inbound workflow (v2_1).

Chains the existing workflows to execute the full inbound pipeline:
1. Identify entity types from the inbound query + knowledge text
2. For each entity type, try to find an existing blueprint (or create one)
3. For each blueprint, identify all entity instances in the knowledge text
4. For each entity, fill the blueprint attributes
"""
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from workflow.inbound_v2_1.blueprint_entity_identify_workflow import BlueprintEntityIdentifyWorkflow
from workflow.inbound_v2_1.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.inbound_v2_1.blueprint_identify_workflow import BlueprintIdentifyWorkflow
from workflow.inbound_v2_1.entity_type_identify_workflow import EntityIdentifyWorkflow
from workflow.inbound_v2_1.fill_blueprint_workflow import FillBlueprintWorkflow
from workflow.inbound_v2_1.persist_knowledge_workflow import PersistKnowledgeWorkflow
from workflow.workflow_base import WorkflowBase


class InboundOrchestrator(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.inbound_query = ""
        self.knowledge_text = ""
        self.bucket_name = ""

    async def build(self, inbound_query: str, knowledge_text: str, bucket_name: str):
        self.inbound_query = inbound_query
        self.knowledge_text = knowledge_text
        self.bucket_name = bucket_name
        return self

    async def execute(self) -> list[dict]:
        """
        Returns: list of filled instances [{
            "blueprint_name": str,
            "entity_name": str,
            "entity_desc": str,
            "filled_attributes": dict
        }]
        """
        self.append_log("InboundOrchestrator started")
        self.append_log(f"Bucket: {self.bucket_name}")
        self.append_log(f"Query: {self.inbound_query}")

        # Step 1: Identify entity types
        entity_types = await self.execute_subflow(
            EntityIdentifyWorkflow,
            self.inbound_query,
            self.knowledge_text
        )
        self.append_log(f"Identified {len(entity_types)} entity types")

        # Step 2: For each entity type, find or create blueprint
        blueprints = []
        for entity_type in entity_types:
            matched_names = await self.execute_subflow(
                BlueprintIdentifyWorkflow,
                entity_type,
                self.bucket_name
            )

            if matched_names:
                existing = await KnowledgeAccessor.get_blueprint_list(self.bucket_name)
                for bp in existing:
                    if bp.name in matched_names:
                        blueprints.append(bp)
                        self.append_log(f"Reusing blueprint: {bp.name}")
            else:
                new_bp = await self.execute_subflow(
                    BlueprintGenerationWorkflow,
                    entity_type['type_name'],
                    entity_type['locate_reason'],
                    self.inbound_query,
                    self.knowledge_text,
                    self.bucket_name
                )
                new_bp.blueprint_id = await KnowledgeAccessor.create_blueprint(new_bp)
                blueprints.append(new_bp)
                self.append_log(f"Created blueprint: {new_bp.name} (id={new_bp.blueprint_id})")

        # Step 3: For each blueprint, identify all entity instances
        filled_instances = []
        for blueprint in blueprints:
            entities = await self.execute_subflow(
                BlueprintEntityIdentifyWorkflow,
                blueprint,
                self.knowledge_text
            )
            self.append_log(f"Blueprint {blueprint.name}: {len(entities)} entities")

            # Step 4: For each entity, fill the blueprint then persist with collision check
            for entity in entities:
                filled_attributes = await self.execute_subflow(
                    FillBlueprintWorkflow,
                    blueprint,
                    entity['entity_name'],
                    entity['entity_desc'],
                    self.knowledge_text
                )
                self.append_log(f"Filled: {blueprint.name} / {entity['entity_name']}")

                # Step 5: Collision detection + persist
                persist_result = await self.execute_subflow(
                    PersistKnowledgeWorkflow,
                    blueprint,
                    filled_attributes
                )

                filled_instances.append({
                    "blueprint_name": blueprint.name,
                    "entity_name": entity['entity_name'],
                    "entity_desc": entity['entity_desc'],
                    "filled_attributes": filled_attributes,
                    "persisted": persist_result["persisted"],
                    "collision": persist_result["collision"],
                })
                if persist_result["persisted"]:
                    self.append_log(f"Persisted: {entity['entity_name']}")
                else:
                    self.append_log(f"Collision: {entity['entity_name']} - {persist_result['collision']['reason']}")

        self.append_log(f"InboundOrchestrator completed: {len(filled_instances)} instances")
        return filled_instances