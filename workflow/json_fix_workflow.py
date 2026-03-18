"""
Fix malformed JSON using LLM
"""
import json

from dynamic_agent_service.agent.language_engine import LanguageEngine
from workflow.workflow_base import WorkflowBase

SYSTEM_PROMPT = """Fix the following malformed JSON. Output ONLY valid JSON, nothing else.

Malformed JSON:
{raw}"""


class JsonFixWorkflow(WorkflowBase):

    def __init__(self, language_engine: LanguageEngine, raw: str):
        super().__init__()
        self.language_engine = language_engine
        self.raw = raw

    async def execute(self) -> dict:
        self._append_log(f"Fixing JSON ({len(self.raw)} chars)")
        prompt = SYSTEM_PROMPT.format(raw=self.raw)
        result = await self.language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        self._append_log("JSON fixed")
        return json.loads(result)
