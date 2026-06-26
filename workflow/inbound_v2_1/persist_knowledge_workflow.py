"""
Collision detection and persistence for filled blueprint instances.

Pipeline: embed identifier -> search top_k=3 existing identifiers -> LLM decides collision -> persist if no collision

Input: Blueprint, filled_attributes, entity_name
Output: persist result with collision info
"""
import json
import uuid

from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.inbound_v2_1.merge_knowledge_workflow import MergeKnowledgeWorkflow
from workflow.workflow_base import WorkflowBase


COLLISION_SYSTEM_PROMPT = """You are a collision detection agent.

You decide whether a new entity instance is describing the same real-world thing as an existing instance in the knowledge base.

Rules:
- Two instances COLLIDE if they refer to the same real-world entity, even if described differently.
- Two instances do NOT collide if they are genuinely different entities that happen to share similar names or attributes.
- Focus on the identifier and core content, not superficial wording differences.
"""

COLLISION_USER_PROMPT = """New instance to insert:
{new_instance_json}

Existing instances in the knowledge base:
{existing_instances_json}

Does the new instance collide with any existing instance?

Respond with ONLY valid JSON:
{{"collides": true/false, "collides_with": "instance_id or null", "reason": "brief explanation"}}
"""


class PersistKnowledgeWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.blueprint = None
        self.filled_attributes = {}

    async def build(self, blueprint: Blueprint, filled_attributes: dict[str, str]):
        self.blueprint = blueprint
        self.filled_attributes = filled_attributes
        return self

    async def execute(self) -> dict:
        """
        Returns: {"persisted": bool, "instance_id": str|None, "collision": dict|None}
        """
        self.append_log("SolveCollisionWorkflow started")

        # Step 1: Search for similar identifiers
        candidates = await self._search_similar_identifiers()

        # Step 2: If candidates found, ask LLM to decide collision
        if candidates:
            self.append_log(f"Found {len(candidates)} candidate instances")
            collision = await self._detect_collision(candidates)

            if collision["collides"]:
                self.append_log(f"Collision detected: {collision['reason']}")
                instance_id = await self._merge_collision(candidates, collision)
                return {"persisted": True, "instance_id": instance_id, "collision": collision, "merged": True}

        # Step 3: No collision, persist
        instance_id = await self._persist()
        self.append_log(f"Persisted instance: {instance_id}")
        return {"persisted": True, "instance_id": instance_id, "collision": None, "merged": False}

    async def _search_similar_identifiers(self) -> list[dict]:
        """Search top_k=3 existing instances by identifier embedding."""
        identifier_name = next(
            name for name, attr in self.blueprint.attributes.items()
            if attr.is_identifier
        )
        identifier_value = self.filled_attributes.get(identifier_name, "")
        if not identifier_value:
            return []

        # Get identifier attribute_id for filtering
        blueprint_attrs = await KnowledgeAccessor.get_attributes(self.blueprint.blueprint_id)
        identifier_attr_id = next(
            (a.attribute_id for a in blueprint_attrs if a.name == identifier_name), None
        )
        if not identifier_attr_id:
            return []

        # Embed and search
        embeddings = await KnowledgeEngine.get_embeddings([identifier_value])
        collection_name = f"bucket_{self.blueprint.bucket_name.replace('-', '_')}"
        client = MilvusInstance.get_client()

        if not client.has_collection(collection_name):
            return []

        results = MilvusInstance.hybrid_search(
            collection_name=collection_name,
            query_vector=embeddings[0],
            query_text=identifier_value,
            top_k=3,
            embedding_weight=1.0,
            bm25_weight=0.0,
            output_fields=["instance_id", "value"],
        )

        # Pull full instances for each unique instance_id
        instance_ids = list({r["instance_id"] for r in results})
        if not instance_ids:
            return []

        return await self._get_full_instances(instance_ids)

    async def _get_full_instances(self, instance_ids: list[str]) -> list[dict]:
        """Pull full attribute values for given instance_ids from Milvus."""
        collection_name = f"bucket_{self.blueprint.bucket_name.replace('-', '_')}"
        client = MilvusInstance.get_client()

        blueprint_attrs = await KnowledgeAccessor.get_attributes(self.blueprint.blueprint_id)
        attr_id_to_name = {a.attribute_id: a.name for a in blueprint_attrs}

        id_list = ", ".join(f'"{iid}"' for iid in instance_ids)
        nodes = client.query(
            collection_name=collection_name,
            filter=f"instance_id in [{id_list}]",
            output_fields=["instance_id", "attribute_id", "value"],
        )

        instances = {iid: {"instance_id": iid} for iid in instance_ids}
        for n in nodes:
            iid = n["instance_id"]
            attr_name = attr_id_to_name.get(n["attribute_id"])
            if attr_name and iid in instances:
                instances[iid][attr_name] = n["value"]
        return list(instances.values())

    async def _detect_collision(self, candidates: list[dict]) -> dict:
        """Ask LLM whether the new instance collides with any candidate."""
        new_instance_json = json.dumps(self.filled_attributes, ensure_ascii=False, indent=2)
        existing_json = json.dumps(candidates, ensure_ascii=False, indent=2)

        user_prompt = COLLISION_USER_PROMPT.format(
            new_instance_json=new_instance_json,
            existing_instances_json=existing_json,
        )
        raw = await self.invoke_agent([
            {"role": "system", "content": COLLISION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ])

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"collides": False, "collides_with": None, "reason": "parse error"}

    async def _merge_collision(self, candidates: list[dict], collision: dict) -> str:
        """Merge incoming attributes into the collided existing instance."""
        target_id = collision.get("collides_with")
        existing = next((c for c in candidates if c.get("instance_id") == target_id), None)
        if existing is None:
            existing = candidates[0]
            target_id = existing["instance_id"]
            collision["collides_with"] = target_id

        merged_attributes = await self.execute_subflow(
            MergeKnowledgeWorkflow,
            self.blueprint,
            existing,
            self.filled_attributes,
            collision,
        )
        await self._replace_instance_attributes(target_id, merged_attributes)
        self.append_log(f"Merged collision into existing instance: {target_id}")
        return target_id

    async def _replace_instance_attributes(self, instance_id: str, filled_attributes: dict[str, str]):
        """Replace Milvus attribute nodes for an existing instance."""
        existing_nodes = KnowledgeAccessor.get_nodes_by_instance_id(self.blueprint.bucket_name, instance_id)
        existing_ids = [node["kn_id"] for node in existing_nodes]
        if existing_ids:
            KnowledgeAccessor.delete_by_ids(self.blueprint.bucket_name, existing_ids)

        await self._upsert_attribute_nodes(instance_id, filled_attributes)

    async def _persist(self) -> str:
        """Persist filled instance to PostgreSQL and Milvus."""
        instance_id = str(uuid.uuid4())

        await KnowledgeAccessor.create_instance(instance_id, self.blueprint.blueprint_id)
        await self._upsert_attribute_nodes(instance_id, self.filled_attributes)
        return instance_id

    async def _upsert_attribute_nodes(self, instance_id: str, filled_attributes: dict[str, str]):
        """Upsert one Milvus knowledge node per persisted blueprint attribute."""
        blueprint_attrs = await KnowledgeAccessor.get_attributes(self.blueprint.blueprint_id)
        attr_name_to_id = {attr.name: attr.attribute_id for attr in blueprint_attrs}

        persistable_items = [
            (attr_name, value)
            for attr_name, value in filled_attributes.items()
            if attr_name in attr_name_to_id and value is not None
        ]
        values = [value for _, value in persistable_items]
        if not values:
            return

        embeddings = await KnowledgeEngine.get_embeddings(values)

        entities = []
        for i, (attr_name, value) in enumerate(persistable_items):
            entities.append({
                "kn_id": str(uuid.uuid4()),
                "instance_id": instance_id,
                "attribute_id": attr_name_to_id[attr_name],
                "value": value,
                "embedding": embeddings[i]
            })

        KnowledgeAccessor.upsert_entities(self.blueprint.bucket_name, entities)
        self.append_log(f"Upserted {len(entities)} entities to Milvus")
