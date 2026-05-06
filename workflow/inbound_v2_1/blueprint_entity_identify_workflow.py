"""
Identify all existing entities of a blueprint type from knowledge text.

This workflow takes a blueprint and knowledge text, then identifies all entities
that match the blueprint type. For each entity found, it returns:
- entity_name: The identifier value (e.g., the name of the product/exploit)
- entity_desc: A brief description of what this specific entity is

Input: Blueprint, knowledge text
Output: list[dict] with {"entity_name": str, "entity_desc": str}
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


IDENTIFY_ENTITIES_PROMPT = """Identify all existing entities of the specified type from the knowledge text.

Blueprint Type: {blueprint_name}
Blueprint Description: {blueprint_description}

Identifier Attribute: {identifier_name}
Identifier Description: {identifier_description}

All Blueprint Attributes:
{all_attributes}

Knowledge Text:
{knowledge_text}

Identify ALL entities of type "{blueprint_name}" that exist in the knowledge text.
For each entity, provide:
1. entity_name: A meaningful, human-readable name for this entity
2. entity_desc: A brief description of what this specific entity is (1-2 sentences)

Output ONLY valid JSON list:
[
  {{
    "entity_name": "meaningful name",
    "entity_desc": "brief description of this specific entity"
  }},
  ...
]

Rules:
- Only include entities where the text provides enough information to fill at least 2-3 attributes from the blueprint (beyond just the identifier)
- entity_name should be meaningful and human-readable
  - For products: use the actual product name (e.g., "FreeBSD", "Firefox", "OpenBSD")
  - For exploits: create a descriptive name based on what it does (e.g., "FreeBSD NFS RCE", "Firefox JIT Heap Spray")
  - Avoid using technical IDs like SHA-3 hashes or long cryptographic strings as names
  - If a CVE ID exists, you may use it (e.g., "CVE-2026-4747")
- entity_desc should briefly describe this specific entity, not the type in general
- If no entities are found, return an empty list []
- Keep entity_desc concise (1-2 sentences)
- Prioritize clarity and readability in entity names
"""


class BlueprintEntityIdentifyWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.blueprint = None
        self.knowledge_text = ""

    async def build(self, blueprint: Blueprint, knowledge_text: str):
        self.blueprint = blueprint
        self.knowledge_text = knowledge_text
        return self

    async def execute(self) -> list[dict]:
        """
        Returns: list of {"entity_name": str, "entity_desc": str}
        """
        self.append_log("BlueprintEntityIdentifyWorkflow started")
        self.append_log(f"Blueprint: {self.blueprint.name}")

        entities = await self._identify_entities()

        self.append_log(f"Identified {len(entities)} entities")
        for i, entity in enumerate(entities, 1):
            self.append_log(f"  Entity {i}: {entity.get('entity_name')}")

        self.append_log("BlueprintEntityIdentifyWorkflow completed")
        return entities

    async def _identify_entities(self) -> list[dict]:
        """
        Use LLM to identify all entities of the blueprint type from knowledge text.
        Returns: list of {"entity_name": str, "entity_desc": str}
        """
        # Find the identifier attribute
        identifier_name = next(
            name for name, attr in self.blueprint.attributes.items()
            if attr.is_identifier
        )
        identifier_description = self.blueprint.attributes[identifier_name].description

        # Format all attributes for the prompt
        all_attributes = {
            name: attr.description
            for name, attr in self.blueprint.attributes.items()
        }

        prompt = IDENTIFY_ENTITIES_PROMPT.format(
            blueprint_name=self.blueprint.name,
            blueprint_description=self.blueprint.description,
            identifier_name=identifier_name,
            identifier_description=identifier_description,
            all_attributes=json.dumps(all_attributes, ensure_ascii=False, indent=2),
            knowledge_text=self.knowledge_text
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            entities = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            entities = await self.execute_subflow(JsonFixWorkflow, raw)

        if not isinstance(entities, list):
            self.append_log(f"Warning: Expected list, got {type(entities)}. Wrapping in list.")
            entities = [entities] if entities else []

        return entities