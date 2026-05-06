"""
Repair malformed JSON strings using code-based fixes first, then LLM fallback.

Takes broken JSON text and tries to fix it programmatically (strip markdown, whitespace, etc).
If that fails, asks LLM to fix it. Returns valid parsed dict.
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

    def _code_fix(self, raw: str) -> dict | None:
        """
        Try to fix JSON programmatically without LLM.
        Returns parsed dict if successful, None if failed.
        """
        self.append_log(f"Attempting code-based JSON fix ({len(raw)} chars)")

        # Try multiple fix strategies
        strategies = [
            lambda s: s,  # Try as-is first
            lambda s: s.strip(),  # Strip whitespace
            self._strip_markdown_fences,  # Strip ```json ``` or ``` ```
            self._strip_markdown_and_whitespace,  # Combined approach
            self._extract_json_object,  # Extract first {...} or [...]
        ]

        for i, strategy in enumerate(strategies, 1):
            try:
                cleaned = strategy(raw)
                if cleaned:
                    result = json.loads(cleaned)
                    self.append_log(f"Code fix succeeded with strategy {i}")
                    return result
            except (json.JSONDecodeError, ValueError, AttributeError):
                continue

        self.append_log("All code fix strategies failed")
        return None

    def _strip_markdown_fences(self, text: str) -> str:
        """Strip markdown code fences like ```json ... ``` or ``` ... ```"""
        text = text.strip()

        # Pattern 1: ```json\n...\n```
        if text.startswith("```json"):
            text = text[7:]  # Remove ```json
            if text.endswith("```"):
                text = text[:-3]
            return text.strip()

        # Pattern 2: ```\n...\n```
        if text.startswith("```"):
            text = text[3:]  # Remove ```
            if text.endswith("```"):
                text = text[:-3]
            return text.strip()

        return text

    def _strip_markdown_and_whitespace(self, text: str) -> str:
        """Strip markdown fences and extra whitespace"""
        text = self._strip_markdown_fences(text)
        return text.strip()

    def _extract_json_object(self, text: str) -> str:
        """Extract first JSON object {...} or array [...] from text"""
        text = text.strip()

        # Try to find first { or [
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start_idx = text.find(start_char)
            if start_idx != -1:
                # Find matching closing bracket
                depth = 0
                for i in range(start_idx, len(text)):
                    if text[i] == start_char:
                        depth += 1
                    elif text[i] == end_char:
                        depth -= 1
                        if depth == 0:
                            return text[start_idx:i+1]

        return text

    async def _llm_fix(self, raw: str) -> dict:
        """Use LLM to fix malformed JSON"""
        self.append_log(f"Attempting LLM-based JSON fix ({len(raw)} chars)")
        prompt = SYSTEM_PROMPT.format(raw=raw)
        result = await self.invoke_agent([{"role": "user", "content": prompt}])

        # Try code fix on LLM result first
        fixed = self._code_fix(result)
        if fixed is not None:
            return fixed

        # If code fix still fails, try parsing LLM result directly
        self.append_log("LLM fix completed")
        return json.loads(result)

    async def execute(self) -> dict:
        # Try code-based fix first
        result = self._code_fix(self.raw)
        if result is not None:
            return result

        # Fall back to LLM fix
        return await self._llm_fix(self.raw)
