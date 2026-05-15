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


FILL_SYSTEM_PROMPT = """You are a RAG chunking agent.

Your job is to extract text from a knowledge document and distribute it into predefined attribute buckets for a specific entity.

Rules:
- Extract and reorganize relevant text from the source document into each attribute.
- Preserve the original wording as much as possible. Do not invent information.
- Each attribute value should be a meaningful text segment (use simple markdown for structure).
- If the source has no relevant content for an attribute, set its value to null.
- The identifier attribute MUST have a value.
- Focus only on information about the target entity, not other entities.
- Do NOT use Python list syntax like ['item'] — use plain text or markdown bullets.
"""

FILL_USER_PROMPT = """Entity: {entity_name}
Entity Description: {entity_desc}

Blueprint: {blueprint_name} — {blueprint_description}

Attributes to fill:
{attributes_json}

Knowledge Text:
{knowledge_text}

Output ONLY valid JSON:
{{
  "attribute_name": "extracted text chunk",
  ...
}}
"""

GENERATE_SUMMARY_PROMPT = """You are generating a summary for a specific instance.

Blueprint: {blueprint_name}

Filled Attributes:
{filled_attributes_json}

Generate a concise summary (2-3 sentences) that captures the key information about this specific instance.

The summary should:
- Provide a quick overview of what this instance is
- Highlight the most important or distinctive attributes
- Be specific to this instance, not generic

Output ONLY the summary text (not JSON, just the text).

Rules:
- Keep it concise (2-3 sentences maximum)
- Focus on the most important information
- Make it specific to this instance
- Use clear, readable language
- ONLY use information from the filled attributes above
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
        Returns: dict of filled attribute values {attribute_name: value} including summary
        """
        self.append_log("FillBlueprintWorkflow started")
        self.append_log(f"Blueprint: {self.blueprint.name}")
        self.append_log(f"Entity: {self.entity_name}")

        # Step 1: Fill all blueprint attributes
        filled_attributes = await self._fill_attributes()

        # Remove null attributes
        filled_attributes = {k: v for k, v in filled_attributes.items() if v is not None}

        self.append_log(f"Filled {len(filled_attributes)} attributes")

        # Step 2: Generate summary by reviewing filled attributes
        summary = await self._generate_summary(filled_attributes)
        filled_attributes['summary'] = summary
        self.append_log(f"Generated summary")

        self.append_log("FillBlueprintWorkflow completed")
        return filled_attributes

    async def _fill_attributes(self) -> dict[str, str]:
        """
        Use LLM to fill all blueprint attributes for the entity.
        Returns: dict of {attribute_name: value}
        """
        attributes_dict = {
            name: attr.description
            for name, attr in self.blueprint.attributes.items()
        }

        user_prompt = FILL_USER_PROMPT.format(
            blueprint_name=self.blueprint.name,
            blueprint_description=self.blueprint.description,
            entity_name=self.entity_name,
            entity_desc=self.entity_desc,
            attributes_json=json.dumps(attributes_dict, ensure_ascii=False, indent=2),
            knowledge_text=self.knowledge_text,
        )

        raw = await self.invoke_agent([
            {"role": "system", "content": FILL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ])

        try:
            filled_attributes = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            filled_attributes = await self.execute_subflow(JsonFixWorkflow, raw)

        return filled_attributes

    async def _generate_summary(self, filled_attributes: dict[str, str]) -> str:
        """
        Generate summary by reviewing all filled attributes.
        Returns: summary string
        """
        self.append_log("Generating summary by reviewing filled attributes")

        prompt = GENERATE_SUMMARY_PROMPT.format(
            blueprint_name=self.blueprint.name,
            filled_attributes_json=json.dumps(filled_attributes, ensure_ascii=False, indent=2)
        )

        summary = await self.invoke_agent([{"role": "user", "content": prompt}])
        return summary.strip()
