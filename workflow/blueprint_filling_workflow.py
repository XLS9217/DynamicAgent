"""
Fill blueprint attributes with actual values from raw knowledge
"""
import json

from workflow.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase

FILL_PROMPT = """Given the attribute schema and raw knowledge, extract the actual values for each attribute.

Attribute Schema:
{attribute_schema}

Raw Knowledge:
{raw_knowledge}

Output ONLY valid JSON: {{"attribute_name": "actual value from raw knowledge", ...}}
Values MUST be in the same language as the raw knowledge."""


class BlueprintFillingWorkflow(WorkflowBase):
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
        self._append_log(f"Filling {len(self.attribute_schema)} attributes")
        raw = await self._language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        self._append_log(f"Filled {len(result)} attributes")
        return result
