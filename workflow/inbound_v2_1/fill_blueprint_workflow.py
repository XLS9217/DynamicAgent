"""
Fill a blueprint with attribute values for a specific entity.

This workflow takes:
- A blueprint (with all attribute definitions)
- An entity (entity_name + entity_desc)
- Knowledge text

And fills all the blueprint attributes with values extracted from the knowledge text.

Input: Blueprint, entity_name, entity_desc, knowledge_text
Output: dict of filled attribute values {attribute_name: value}
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


FILL_BLUEPRINT_PROMPT = """You are filling a blueprint with attribute values for a specific entity.

Blueprint: {blueprint_name}
Blueprint Description: {blueprint_description}

Entity Name: {entity_name}
Entity Description: {entity_desc}

Attributes to fill:
{attributes_json}

Knowledge Text:
{knowledge_text}

Extract and fill ALL attributes for this specific entity from the knowledge text.

Output ONLY valid JSON:
{{
  "attribute_name": "value extracted from text",
  ...
}}

Rules:
- Fill ALL attributes listed above
- Use the original text as much as possible — do not invent information
- You may add markdown formatting (headings, bullet points, bold) to improve readability
- Keep the original language of the source text
- Each value should be independently understandable
- If the source text has no relevant content for an attribute, set its value to null
- The identifier attribute "{identifier_name}" MUST have a value (use the entity_name)
- Focus on information specifically about "{entity_name}", not other entities
"""


class FillBlueprintWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.blueprint = None
        self.entity_name = ""
        self.entity_desc = ""
        self.knowledge_text = ""

    async def build(self, blueprint: Blueprint, entity_name: str, entity_desc: str, knowledge_text: str):
        self.blueprint = blueprint
        self.entity_name = entity_name
        self.entity_desc = entity_desc
        self.knowledge_text = knowledge_text
        return self

    async def execute(self) -> dict[str, str]:
        """
        Returns: dict of filled attribute values {attribute_name: value}
        """
        self.append_log("FillBlueprintWorkflow started")
        self.append_log(f"Blueprint: {self.blueprint.name}")
        self.append_log(f"Entity: {self.entity_name}")

        filled_attributes = await self._fill_attributes()

        # Validate identifier is present
        identifier_name = next(
            name for name, attr in self.blueprint.attributes.items()
            if attr.is_identifier
        )
        if identifier_name not in filled_attributes or not filled_attributes[identifier_name]:
            self.append_log(f"Warning: Identifier '{identifier_name}' missing, using entity_name")
            filled_attributes[identifier_name] = self.entity_name

        # Remove null attributes
        filled_attributes = {k: v for k, v in filled_attributes.items() if v is not None}

        self.append_log(f"Filled {len(filled_attributes)} attributes")
        self.append_log("FillBlueprintWorkflow completed")
        return filled_attributes

    async def _fill_attributes(self) -> dict[str, str]:
        """
        Use LLM to fill all blueprint attributes for the entity.
        Returns: dict of {attribute_name: value}
        """
        # Find identifier attribute
        identifier_name = next(
            name for name, attr in self.blueprint.attributes.items()
            if attr.is_identifier
        )

        # Format attributes for the prompt
        attributes_dict = {
            name: attr.description
            for name, attr in self.blueprint.attributes.items()
        }

        prompt = FILL_BLUEPRINT_PROMPT.format(
            blueprint_name=self.blueprint.name,
            blueprint_description=self.blueprint.description,
            entity_name=self.entity_name,
            entity_desc=self.entity_desc,
            attributes_json=json.dumps(attributes_dict, ensure_ascii=False, indent=2),
            knowledge_text=self.knowledge_text,
            identifier_name=identifier_name
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            filled_attributes = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            filled_attributes = await self.execute_subflow(JsonFixWorkflow, raw)

        return filled_attributes