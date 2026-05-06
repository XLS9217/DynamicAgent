"""
Extract multiple instances from knowledge text for a given blueprint.

Takes a blueprint schema and raw source text, then uses LLM to extract ALL matching
instances from the text. Returns a list of filled instances, where each instance is
a dict of attribute values.
"""
import json

from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase

MULTI_FILL_PROMPT = """You are a RAG chunking agent.
Your task is to extract ALL instances of {blueprint_name} from the knowledge text.

{guidance_section}

Knowledge Text:
{raw_knowledge}

Blueprint: {blueprint_name}
Description: {blueprint_description}

Attributes to fill for each instance:
{attribute_schema}

IMPORTANT:
- Extract ALL instances of {blueprint_name} found in the text
- For each instance, the attribute "{identifier_name}" is the identifier and MUST NOT be null
- If an attribute doesn't exist in the text for an instance, set it to null
- Return a JSON list of instances

Output ONLY valid JSON:
[
  {{"attribute_name": "value", ...}},
  {{"attribute_name": "value", ...}},
  ...
]

Rules:
- Use the original text as much as possible — do not invent information
- You may add markdown formatting (headings, bullet points, bold) to improve readability
- Keep the original language of the source text
- Each instance's identifier attribute "{identifier_name}" MUST have a value
- If no instances are found, return an empty list []
"""


class BlueprintMultiFillingWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.blueprint_name = ""
        self.blueprint_description = ""
        self.attribute_schema = {}
        self.raw_knowledge = ""
        self.identifier_name = None
        self.enriched_query = None

    async def build(self, blueprint_name: str, blueprint_description: str, attribute_schema: dict[str, str],
                    raw_knowledge: str, identifier_name: str, enriched_query: str = None):
        self.blueprint_name = blueprint_name
        self.blueprint_description = blueprint_description
        self.attribute_schema = attribute_schema
        self.raw_knowledge = raw_knowledge
        self.identifier_name = identifier_name
        self.enriched_query = enriched_query
        return self

    async def execute(self) -> list[dict[str, str]]:
        """
        Returns: list of instances, where each instance is a dict of attribute values
        """
        instances = await self._fill_all()

        # Validate each instance
        valid_instances = []
        for i, instance in enumerate(instances):
            if self.identifier_name in instance and instance[self.identifier_name]:
                # Remove null attributes
                instance = {k: v for k, v in instance.items() if v is not None}
                valid_instances.append(instance)
                self.append_log(f"  Instance {i+1}: {instance.get(self.identifier_name)}")
            else:
                self.append_log(f"  Skipping instance {i+1}: missing identifier")

        self.append_log(f"Extracted {len(valid_instances)} valid instances")
        return valid_instances

    async def _fill_all(self) -> list[dict[str, str]]:
        guidance_section = ""
        if self.enriched_query:
            guidance_section = f"Guidance: {self.enriched_query}\n\n"

        prompt = MULTI_FILL_PROMPT.format(
            blueprint_name=self.blueprint_name,
            blueprint_description=self.blueprint_description,
            guidance_section=guidance_section,
            attribute_schema=json.dumps(self.attribute_schema, ensure_ascii=False, indent=2),
            raw_knowledge=self.raw_knowledge,
            identifier_name=self.identifier_name
        )

        self.append_log(f"Extracting all {self.blueprint_name} instances from knowledge text")
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        if not isinstance(result, list):
            self.append_log(f"Warning: Expected list, got {type(result)}. Wrapping in list.")
            result = [result] if result else []

        return result