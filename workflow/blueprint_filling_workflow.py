"""
Fill blueprint attributes by chunking relevant original text from raw knowledge
"""
import json

from workflow.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase

FILL_PROMPT = """You are a RAG chunking agent.
Your task is to extract relevant content from the source for each attribute, and organize it into readable markdown.

Source Text:
{raw_knowledge}

Attributes to fill:
{attribute_schema}

IMPORTANT: The attribute "{identifier_name}" is the identifier and MUST NOT be null. Extract it from the source.

Output ONLY valid JSON: {{"attribute_name": "markdown formatted content", ...}}
Rules:
- Use the original text as much as possible — do not invent information
- You may reorder, deduplicate, and add markdown formatting (headings, bullet points, bold) to improve readability
- You may add brief transitional phrases to connect scattered pieces, but the substance must come from the source
- Keep the original language of the source text
- Each value should be independently understandable
- If the source text has no relevant content for a non-identifier attribute, set its value to null
- The identifier attribute "{identifier_name}" MUST have a value"""

FILL_IDENTIFIER_PROMPT = """You previously failed to extract the identifier attribute "{identifier_name}".

Source Text:
{raw_knowledge}

Identifier attribute description: {identifier_description}

Extract ONLY the identifier value. Output a single short string (not JSON), just the value itself."""


class BlueprintFillingWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.attribute_schema = {}
        self.raw_knowledge = ""
        self.identifier_name = None

    async def build(self, attribute_schema: dict[str, str], raw_knowledge: str, identifier_name: str):
        self.attribute_schema = attribute_schema
        self.raw_knowledge = raw_knowledge
        self.identifier_name = identifier_name
        return self

    async def execute(self) -> dict[str, str]:
        result = await self._fill()
        self._validate(result)

        if self.identifier_name not in result or not result[self.identifier_name]:
            self.append_log(f"Identifier '{self.identifier_name}' missing, attempting targeted extraction")
            result[self.identifier_name] = await self._fill_identifier()
            self._validate(result)

        result = {k: v for k, v in result.items() if v is not None}
        self.append_log(f"Filled {len(result)} attributes")
        return result

    async def _fill(self) -> dict[str, str]:
        prompt = FILL_PROMPT.format(
            attribute_schema=json.dumps(self.attribute_schema, ensure_ascii=False, indent=2),
            raw_knowledge=self.raw_knowledge,
            identifier_name=self.identifier_name
        )
        self.append_log(f"Filling {len(self.attribute_schema)} attributes")
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        return result

    def _validate(self, result: dict[str, str]):
        if self.identifier_name not in result or not result[self.identifier_name]:
            raise ValueError(f"Identifier attribute '{self.identifier_name}' is missing or null after filling")

    async def _fill_identifier(self) -> str:
        prompt = FILL_IDENTIFIER_PROMPT.format(
            identifier_name=self.identifier_name,
            identifier_description=self.attribute_schema[self.identifier_name],
            raw_knowledge=self.raw_knowledge
        )
        result = await self.invoke_agent([{"role": "user", "content": prompt}])
        return result.strip()
