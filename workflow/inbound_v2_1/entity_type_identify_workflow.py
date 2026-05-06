"""
Identify entity types from inbound query and knowledge text.

This workflow analyzes the inbound query to identify what entity types the user wants to extract.
It leans heavily on the inbound query, but also has access to the knowledge text for context.

Flow:
1. Parse the inbound query to identify entity types
2. For each entity type, extract:
   - Type name (e.g., "Product", "Exploit", "Person")
   - Locate reason - why this entity type was identified and how it exists in the text
3. Return list of entity types

Output: list[dict] with {"type_name": str, "locate_reason": str}
"""
import json

from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


IDENTIFY_ENTITY_TYPES_PROMPT = """Analyze the inbound query and identify what entity types the user wants to extract.

User Query: {inbound_query}

Knowledge Text (for context):
{knowledge_text}

Identify the entity types mentioned in text. For each type, provide:
1. Type name (e.g., "Product", "Exploit", "Person", "Company")
2. Locate reason - explain why this entity type was identified and how it exists in the text

Output as JSON list:
[
  {{
    "type_name": "EntityType",
    "locate_reason": "why this entity type was identified and how it exists in the text"
  }},
  ...
]

Rules:
- Extract entity TYPES, not instances
- Use singular form (e.g., "Product" not "Products")
- Keep type names generic and reusable
- The knowledge text is provided for context, but lean on the query first
- If the query is vague, you may reference the knowledge text to infer entity types
- In locate_reason, explain both WHY you identified this type (based on the query) and HOW it appears in the text (based on the knowledge text)
"""


class EntityIdentifyWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.inbound_query = ""
        self.knowledge_text = ""

    async def build(self, inbound_query: str, knowledge_text: str):
        self.inbound_query = inbound_query
        self.knowledge_text = knowledge_text
        return self

    async def execute(self) -> list[dict]:
        """
        Returns: list of {"type_name": str, "locate_reason": str}
        """
        self.append_log("EntityIdentifyWorkflow started")
        self.append_log(f"Inbound query: {self.inbound_query}")

        entity_types = await self._identify_entity_types()

        self.append_log(f"Identified {len(entity_types)} entity types")
        for i, et in enumerate(entity_types, 1):
            self.append_log(f"  Type {i}: {et.get('type_name')}")
            self.append_log(f"    Reason: {et.get('locate_reason')}")

        self.append_log("EntityIdentifyWorkflow completed")
        return entity_types

    async def _identify_entity_types(self) -> list[dict]:
        """
        Use LLM to identify entity types from the inbound query and knowledge text.
        Returns: list of {"type_name": str, "locate_reason": str}
        """
        prompt = IDENTIFY_ENTITY_TYPES_PROMPT.format(
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text
        )
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            entity_types = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            entity_types = await self.execute_subflow(JsonFixWorkflow, raw)

        return entity_types