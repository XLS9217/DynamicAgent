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

Output ONLY valid JSON: {{"attribute_name": "markdown formatted content", ...}}
Rules:
- Use the original text as much as possible — do not invent information
- You may reorder, deduplicate, and add markdown formatting (headings, bullet points, bold) to improve readability
- You may add brief transitional phrases to connect scattered pieces, but the substance must come from the source
- Keep the original language of the source text
- Each value should be independently understandable
- If the source text has no relevant content for an attribute, set its value to null"""


class BlueprintFillingWorkflow(WorkflowBase):
    # TODO: use is_identifier from BlueprintAttributeSchema to prioritize identifier attributes during filling
    def __init__(self):
        super().__init__()
        self.attribute_schema = {}
        self.raw_knowledge = ""

    async def build(self, attribute_schema: dict[str, str], raw_knowledge: str):
        self.attribute_schema = attribute_schema
        self.raw_knowledge = raw_knowledge
        return self

    async def execute(self) -> dict[str, str]:
        prompt = FILL_PROMPT.format(
            attribute_schema=json.dumps(self.attribute_schema, ensure_ascii=False, indent=2),
            raw_knowledge=self.raw_knowledge
        )
        self.append_log(f"Filling {len(self.attribute_schema)} attributes")
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        result = {k: v for k, v in result.items() if v is not None}
        self.append_log(f"Filled {len(result)} attributes")
        return result
