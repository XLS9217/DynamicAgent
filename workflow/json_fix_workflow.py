"""
Fix malformed JSON using LLM
"""
import json

from dynamic_agent_service.agent.language_engine import LanguageEngine

SYSTEM_PROMPT = """Fix the following malformed JSON. Output ONLY valid JSON, nothing else.

Malformed JSON:
{raw}"""


class JsonFixWorkflow:

    def __init__(self, language_engine: LanguageEngine, raw: str):
        self.language_engine = language_engine
        self.raw = raw

    async def execute(self) -> dict:
        prompt = SYSTEM_PROMPT.format(raw=self.raw)
        result = await self.language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        return json.loads(result)