"""
Fix malformed JSON using LLM
"""
import json

from workflow.workflow_base import WorkflowBase

SYSTEM_PROMPT = """Fix the following malformed JSON. Output ONLY valid JSON, nothing else.

Malformed JSON:
{raw}"""


class JsonFixWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.raw = ""

    async def build(self, raw: str):
        self.raw = raw
        return self

    async def execute(self) -> dict:
        self.append_log(f"Fixing JSON ({len(self.raw)} chars)")
        prompt = SYSTEM_PROMPT.format(raw=self.raw)
        result = await self.invoke_agent([{"role": "user", "content": prompt}])
        self.append_log("JSON fixed")
        return json.loads(result)
