from workflow.blueprint_filling_workflow import BlueprintFillingWorkflow
from workflow.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.blueprint_matching_workflow import BlueprintMatchingWorkflow
from workflow.file_textification_workflow import FileTextificationWorkflow
from workflow.workflow_base import WorkflowBase
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.knowledge.knowledge_node_accessor import KnowledgeNodeAccessor

import json
import uuid

MERGE_PROMPT = """You are merging two versions of the same attribute for a knowledge record.
Combine them into one coherent, deduplicated markdown text.

Attribute: {attr_name}

Existing content:
{old_value}

New content:
{new_value}

Rules:
- Merge both into a single coherent text, removing duplicates
- Keep all unique information from both versions
- Use markdown formatting for readability
- Keep the original language of the source text
- Do not invent information — only use what is provided
- Output ONLY the merged text, no explanation"""

COLLISION_PROMPT = """You are checking if a new knowledge record refers to the same entity as an existing one.

New identifier value: {new_value}

Existing identifier values:
{candidates}

Does the new value refer to the same entity as any of the existing values?
If yes, respond with ONLY the matching existing value exactly as written.
If no, respond with ONLY: NONE"""


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
                self._blueprint_schema.id = await self.knowledge_accessor.create_blueprint(self._blueprint_schema)
                self.append_log(f"Saved new blueprint: {self._blueprint_schema.name} ({self._blueprint_schema.id})")

        self.append_log(f"Using blueprint: {self._blueprint_schema.name} with {len(self._blueprint_schema.attributes)} attributes")

        identifier_name = next(k for k, v in self._blueprint_schema.attributes.items() if v.is_identifier)
        self._filled_blueprint = await self.execute_subflow(
            BlueprintFillingWorkflow,
            {k: v.description for k, v in self._blueprint_schema.attributes.items()},
            self._raw_knowledge_text,
            identifier_name
        )
        self.append_log(f"Filled {len(self._filled_blueprint)} blueprint attributes")

        if self.knowledge_accessor and self._blueprint_schema.id:
            await self._persist_instance()

        self.append_log("Knowledge inbound completed")

        return {
            "query": self.inbound_query,
            "blueprint": self._blueprint_schema.model_dump(),
            "attribute_values": self._filled_blueprint
        }

    async def _persist_instance(self):
        attrs = await self.knowledge_accessor.get_attributes(self._blueprint_schema.id)
        attr_name_to_id = {a.name: a.id for a in attrs}
        identifier_name = next(k for k, v in self._blueprint_schema.attributes.items() if v.is_identifier)
        identifier_value = self._filled_blueprint.get(identifier_name, "")

        # Collect existing identifier values
        existing = await self.knowledge_accessor.get_instances_by_blueprint(self._blueprint_schema.id)
        candidates = {}  # identifier_value -> instance dict
        for inst in existing:
            id_row_id = inst["attributes"].get(identifier_name)
            if not id_row_id:
                continue
            entities = KnowledgeNodeAccessor.get_by_ids([id_row_id])
            if entities:
                candidates[entities[0]["value"]] = inst

        # Ask agent to decide collision
        matched_instance = None
        if candidates:
            candidates_text = "\n".join(f"- {v}" for v in candidates.keys())
            prompt = COLLISION_PROMPT.format(new_value=identifier_value, candidates=candidates_text)
            answer = (await self.invoke_agent([{"role": "user", "content": prompt}])).strip()
            self.append_log(f"Collision check: '{identifier_value}' -> '{answer}'")
            if answer != "NONE":
                matched_instance = candidates.get(answer)

        if matched_instance:
            await self._merge_instance(matched_instance, attr_name_to_id)
        else:
            await self._create_instance(attr_name_to_id)

    async def _create_instance(self, attr_name_to_id: dict[str, str]):
        filled_attr_ids = [
            attr_name_to_id[name]
            for name in self._filled_blueprint
            if name in attr_name_to_id
        ]

        instance_id = str(uuid.uuid4())
        instance_row_ids = await self.knowledge_accessor.create_instance(instance_id, filled_attr_ids)
        self.append_log(f"Created instance {instance_id} with {len(filled_attr_ids)} attributes")

        filled_names = [name for name in self._filled_blueprint if name in attr_name_to_id]
        filled_values = [self._filled_blueprint[name] for name in filled_names]
        embeddings = await KnowledgeEngine.get_embeddings(filled_values)

        entities = [
            {"id": row_id, "instance_id": instance_id, "value": value, "embedding": embedding}
            for row_id, value, embedding in zip(instance_row_ids, filled_values, embeddings)
        ]
        KnowledgeNodeAccessor.upsert_entities(entities)
        self.append_log(f"Upserted {len(entities)} entities to Milvus")

    async def _merge_instance(self, existing: dict, attr_name_to_id: dict[str, str]):
        instance_id = existing["instance_id"]
        existing_row_ids = list(existing["attributes"].values())
        existing_entities = KnowledgeNodeAccessor.get_by_ids(existing_row_ids)
        existing_values = {e["id"]: e["value"] for e in existing_entities}

        to_upsert = []
        new_attr_ids = []

        for name, new_value in self._filled_blueprint.items():
            if name not in attr_name_to_id:
                continue
            row_id = existing["attributes"].get(name)
            if row_id:
                old_value = existing_values.get(row_id, "")
                prompt = MERGE_PROMPT.format(attr_name=name, old_value=old_value, new_value=new_value)
                merged = await self.invoke_agent([{"role": "user", "content": prompt}])
                to_upsert.append({"row_id": row_id, "value": merged.strip()})
            else:
                new_attr_ids.append(attr_name_to_id[name])
                to_upsert.append({"attr_id": attr_name_to_id[name], "value": new_value})

        # Create new instance rows for attributes not yet in this instance
        new_row_ids = []
        if new_attr_ids:
            new_row_ids = await self.knowledge_accessor.create_instance(instance_id, new_attr_ids)

        # Build final values list and embed
        all_values = [item["value"] for item in to_upsert]
        embeddings = await KnowledgeEngine.get_embeddings(all_values)

        entities = []
        new_idx = 0
        for item, value, embedding in zip(to_upsert, all_values, embeddings):
            if "row_id" in item:
                row_id = item["row_id"]
            else:
                row_id = new_row_ids[new_idx]
                new_idx += 1
            entities.append({"id": row_id, "instance_id": instance_id, "value": value, "embedding": embedding})

        KnowledgeNodeAccessor.upsert_entities(entities)
        self.append_log(f"Merged instance {instance_id}: updated {len(entities)} entities")