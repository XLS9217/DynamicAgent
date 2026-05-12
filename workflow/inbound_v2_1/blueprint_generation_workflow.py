"""
Generate a blueprint schema from entity type, inbound query, and knowledge text.

This workflow creates a reusable blueprint with:
- One identifier attribute
- Additional attributes as needed

The blueprint is general and reusable, not instance-specific.
Note: The summary attribute is NOT part of the blueprint - it will be generated per instance after filling.

Input: entity type (type_name + locate_reason), inbound query, knowledge text
Output: Blueprint with attributes (excluding summary)
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


GENERATE_BLUEPRINT_PROMPT = """Generate a reusable blueprint schema for the entity type.

Entity Type: {type_name}
Locate Reason: {locate_reason}

Inbound Query: {inbound_query}

Knowledge Text (for reference):
{knowledge_text}

Create a blueprint with:
1. One identifier attribute - uniquely identifies an instance (e.g., name, title, ID)
2. Additional attributes as needed based on the entity type and knowledge text

Design attributes to be information-rich rather than categorical:
- Prefer attributes that capture detailed information over simple labels
- Think of attributes as aspects to extract comprehensive information from the text
- Each attribute is a "bucket" to collect all related information about that aspect
- Avoid yes/no or single-word categorical attributes when possible

Output ONLY valid JSON in this format:
{{
  "name": "CamelCase name for this blueprint type, single word is preferred",
  "description": "A general description of what category/type this blueprint represents, applicable to any instance of this type",
  "attributes": {{
    "attribute_name": {{"description": "description of what this attribute represents", "is_identifier": true}},
    ...
  }}
}}

Rules:
- Description must be general and reusable, not specific to any particular instance
- Attribute names must be in English, lowercase, using underscores
- Exactly one attribute must have is_identifier set to true
- The identifier should be something that uniquely identifies instances (like name, title, id)
"""

VALIDATE_PROMPT = """Review this blueprint schema for quality:

Blueprint:
{blueprint}

Check:
1. Is the description general and reusable (not specific to any instance)?
2. Are attribute names in English, lowercase, with underscores?
3. Are attribute descriptions clear and concise?
4. Is there exactly one attribute with is_identifier set to true?

If ALL checks pass, respond with ONLY: YES
If ANY check fails, respond with ONLY: NO
<issues>
- issue 1
- issue 2
</issues>"""

SUMMARIZE_PROMPT = """You are reviewing a blueprint schema and need to create a summary attribute.

Blueprint Name: {blueprint_name}
Blueprint Description: {blueprint_description}

Existing Attributes:
{attributes_json}

Create a "summary" attribute that will be used to store a short summary of each instance of this blueprint.

The summary attribute should:
- Provide a concise overview of the instance
- Be general enough to apply to any instance of this blueprint type
- Help users quickly understand what the instance is about

Output ONLY the description text for the summary attribute (not JSON, just the description text).

Rules:
- Keep the description concise (1-2 sentences)
- Focus on what the summary should contain, not how to create it
- The description should be general and applicable to any instance
"""


class BlueprintGenerationWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.type_name = ""
        self.locate_reason = ""
        self.inbound_query = ""
        self.knowledge_text = ""
        self.bucket_name = ""

    async def build(self, type_name: str, locate_reason: str, inbound_query: str, knowledge_text: str, bucket_name: str = ""):
        self.type_name = type_name
        self.locate_reason = locate_reason
        self.inbound_query = inbound_query
        self.knowledge_text = knowledge_text
        self.bucket_name = bucket_name
        return self

    async def execute(self) -> Blueprint:
        """
        Returns: Blueprint with attributes (excluding summary)
        """
        self.append_log("BlueprintGenerationWorkflow started")
        self.append_log(f"Entity type: {self.type_name}")

        # Generate blueprint without summary
        blueprint_dict = await self._generate_blueprint()

        self.append_log(f"Generated blueprint: {blueprint_dict['name']}")
        self.append_log(f"  Attributes: {len(blueprint_dict.get('attributes', {}))}")

        # Validate identifier
        # TO-DO: decide whether we need this or not
        # self._validate_identifier(blueprint_dict)

        # Add bucket_name to blueprint_dict
        blueprint_dict['bucket_name'] = self.bucket_name

        self.append_log("BlueprintGenerationWorkflow completed")
        return Blueprint(**blueprint_dict)

    async def _generate_blueprint(self) -> dict:
        """
        Use LLM to generate blueprint schema.
        Returns: dict with name, description, attributes
        """
        prompt = GENERATE_BLUEPRINT_PROMPT.format(
            type_name=self.type_name,
            locate_reason=self.locate_reason,
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text
        )
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            blueprint_dict = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            blueprint_dict = await self.execute_subflow(JsonFixWorkflow, raw)

        return blueprint_dict

    def _validate_identifier(self, blueprint_dict: dict):
        """
        Validate that blueprint has exactly one identifier attribute.
        """
        attributes = blueprint_dict.get("attributes", {})

        # Check identifier count
        identifier_count = sum(1 for attr in attributes.values() if attr.get("is_identifier", False))
        if identifier_count != 1:
            raise ValueError(f"Blueprint must have exactly 1 identifier attribute, found {identifier_count}")

        # Ensure summary is not present yet
        if "summary" in attributes:
            raise ValueError("Blueprint should not have a 'summary' attribute yet - it will be added after")

        self.append_log(f"  Identifier: {next(k for k, v in attributes.items() if v.get('is_identifier'))}")

    async def _generate_summary_desc(self, blueprint_dict: dict) -> str:
        """
        Generate summary attribute description by reviewing the whole blueprint.
        Returns: summary attribute description
        """
        self.append_log("Generating summary attribute by reviewing blueprint")

        # Format existing attributes for the prompt
        attributes_dict = {
            name: {
                "description": attr["description"],
                "is_identifier": attr.get("is_identifier", False)
            }
            for name, attr in blueprint_dict["attributes"].items()
        }

        prompt = SUMMARIZE_PROMPT.format(
            blueprint_name=blueprint_dict['name'],
            blueprint_description=blueprint_dict['description'],
            attributes_json=json.dumps(attributes_dict, ensure_ascii=False, indent=2)
        )

        summary_description = await self.invoke_agent([{"role": "user", "content": prompt}])
        return summary_description.strip()