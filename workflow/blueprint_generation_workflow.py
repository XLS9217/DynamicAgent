"""
Generate blueprint schema (description + attribute:description pairs) from a query
"""
import json

from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase

GENERATE_PROMPT = """Based on this user query, generate a reusable blueprint schema:

User Query: {query}
{raw_text_section}
Output ONLY valid JSON in this format:
{{
  "name": "short_snake_case_name for this blueprint type",
  "description": "A general description of what category/type this blueprint represents, applicable to any instance of this type",
  "attributes": {{
    "attribute_name": "description of what this attribute represents",
    ...
  }}
}}

Rules:
- Description must be general and reusable, not specific to any particular instance
- Attribute names must be in English, lowercase, using underscores
- Keep descriptions concise"""

VALIDATE_PROMPT = """Review this blueprint schema for quality:

User Query: {query}

Blueprint:
{blueprint}

Check:
1. Is the description general and reusable (not specific to any instance)?
2. Are attribute names in English, lowercase, with underscores?
3. Are attributes relevant and sufficient for the query?
4. Are attribute descriptions clear and concise?

If ALL checks pass, respond with ONLY: YES
If ANY check fails, respond with ONLY: NO
<issues>
- issue 1
- issue 2
</issues>"""

REFINE_PROMPT = """Fix the following blueprint schema:

Issues:
{issues}

Original blueprint:
{blueprint}

Output ONLY valid JSON in the same format."""


class BlueprintGenerationWorkflow(WorkflowBase):
    MAX_RETRIES = 2

    def __init__(self, language_engine: LanguageEngine, query: str, raw_text: str = None):
        super().__init__()
        self.language_engine = language_engine
        self.query = query
        self.raw_text = raw_text

    async def _generate(self) -> dict:
        self._append_log("Start generating blueprint schema")
        raw_text_section = ""
        if self.raw_text:
            raw_text_section = f"\nReference Text:\n{self.raw_text}\n"
        prompt = GENERATE_PROMPT.format(query=self.query, raw_text_section=raw_text_section)
        raw = await self.language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        try:
            result = json.loads(raw)
            self._append_log(f"Blueprint generated with {len(result.get('attributes', {}))} attributes")
            return result
        except json.JSONDecodeError:
            self._append_log("Blueprint JSON malformed, invoking JsonFixWorkflow")
            return await self.execute_subflow(JsonFixWorkflow, self.language_engine, raw)

    async def _validate(self, blueprint: dict) -> str | None:
        """Returns None if valid, issues string if not"""
        self._append_log("Validating blueprint quality")
        prompt = VALIDATE_PROMPT.format(
            query=self.query,
            blueprint=json.dumps(blueprint, ensure_ascii=False, indent=2)
        )
        result = await self.language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        if result.strip().startswith("YES"):
            self._append_log("Blueprint validation passed")
            return None
        self._append_log("Blueprint validation failed, refinement required")
        return result

    async def _refine(self, blueprint: dict, issues: str) -> dict:
        self._append_log("Refining blueprint")
        prompt = REFINE_PROMPT.format(
            issues=issues,
            blueprint=json.dumps(blueprint, ensure_ascii=False, indent=2)
        )
        raw = await self.language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        try:
            result = json.loads(raw)
            self._append_log(f"Blueprint refined to {len(result.get('attributes', {}))} attributes")
            return result
        except json.JSONDecodeError:
            self._append_log("Refined blueprint JSON malformed, invoking JsonFixWorkflow")
            return await self.execute_subflow(JsonFixWorkflow, self.language_engine, raw)

    async def execute(self) -> Blueprint:
        """
        Orchestrator: generate -> validate -> refine (max 2 retries)
        """
        self._append_log("BlueprintGenerationWorkflow started")
        blueprint = await self._generate()

        for _ in range(self.MAX_RETRIES):
            issues = await self._validate(blueprint)
            if issues is None:
                break
            blueprint = await self._refine(blueprint, issues)

        self._append_log("BlueprintGenerationWorkflow completed")
        return Blueprint(**blueprint)
