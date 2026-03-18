"""
Fill blueprint attributes with actual values from raw knowledge
"""
import json

from dynamic_agent_service.agent.language_engine import LanguageEngine
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

    def __init__(self, language_engine: LanguageEngine, attribute_schema: dict[str, str], raw_knowledge: str):
        super().__init__()
        self.language_engine = language_engine
        self.attribute_schema = attribute_schema
        self.raw_knowledge = raw_knowledge

    async def execute(self) -> dict[str, str]:
        prompt = FILL_PROMPT.format(
            attribute_schema=json.dumps(self.attribute_schema, ensure_ascii=False, indent=2),
            raw_knowledge=self.raw_knowledge
        )
        self._append_log(f"Filling {len(self.attribute_schema)} attributes")
        raw = await self.language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await JsonFixWorkflow(self.language_engine, raw).execute()

        self._append_log(f"Filled {len(result)} attributes")
        return result
