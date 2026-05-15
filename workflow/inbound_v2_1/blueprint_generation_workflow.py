"""
Generate a blueprint schema from entity type, inbound query, and knowledge text.

Pipeline: generate -> validate (self-reflection) -> refine (if needed)

Input: entity type (type_name + locate_reason), inbound query, knowledge text
Output: Blueprint with attributes (excluding summary)
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


BLUEPRINT_SYSTEM_PROMPT = """You are a designing a blueprint

A blueprint defines a reusable schema for a category of entities.
It has a name, description, and a set of attributes.

Format rules:
- Attribute names: English, lowercase, underscores, generic across all entities of same type.
- Attribute names must be a single concept. Never use "or" to join two words. If they are different things, split into separate attributes. If they are similar, pick the more general word.
- Keep content attributes to 3-9. The identifier attribute is just a short name/label and does not count.
- Exactly one attribute must have is_identifier=true. It holds the entity's unique name.
- Do NOT include a "summary" attribute — it is generated separately.

Content rules:
- The blueprint must be GENERAL: every attribute should apply to ANY instance of this entity type, even from a completely different source text.
- Each content attribute must represent a fundamentally different dimension. If two would often overlap, merge them.
- Design attributes whose filled values would naturally require multi-sentence explanation. Avoid categorical dimensions (type, category, status, vendor) whose values would be one or two words.
- Attribute descriptions should state what content belongs there, not how long or detailed it should be.
"""

OUTPUT_FORMAT = """
Output format (valid JSON only):
{{
  "name": "CamelCase type name, single word preferred",
  "description": "General description of what this type represents",
  "attributes": {{
    "attr_name": {{"description": "what this captures in 1~2 sentence, don't give example", "is_identifier": false}},
    ...
  }}
}}
"""

GENERATE_PROMPT = """Design a blueprint for this entity type.

Entity Type: {type_name}
Locate Reason: {locate_reason}
Inbound Query: {inbound_query}

Knowledge Text (for reference):
{knowledge_text}
""" + OUTPUT_FORMAT

VALIDATE_PROMPT = """Review this blueprint schema by self-reflecting on each attribute.

Blueprint:
{blueprint_json}

For each attribute, ask yourself:
1. Would this attribute make sense for ANY instance of this entity type, even from a completely different text?
2. Is this attribute a fundamentally different dimension from the others, or does it overlap?
3. Is the attribute name generic enough to be reused across different contexts?
4. Does the attribute name contain "or" joining two words? If so, it must be split or simplified.

If ALL attributes pass these checks, respond with ONLY: PASS

If ANY attribute fails, respond with:
FAIL
<issues>
- attribute_name: reason it fails
</issues>
"""

REFINE_PROMPT = """Refine this blueprint based on the validation feedback.

Current Blueprint:
{blueprint_json}

Issues found:
{issues}

Knowledge Text (for reference):
{knowledge_text}

Fix the issues by removing, merging, or renaming attributes.
""" + OUTPUT_FORMAT


class BlueprintGenerationWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.type_name = ""
        self.locate_reason = ""
        self.inbound_query = ""
        self.knowledge_text = ""
        self.bucket_name = ""

    async def build(self, type_name: str, locate_reason: str, inbound_query: str, knowledge_text: str, bucket_name: str = ""):
        self.type_name = type_name
        self.locate_reason = locate_reason
        self.inbound_query = inbound_query
        self.knowledge_text = knowledge_text
        self.bucket_name = bucket_name
        return self

    async def execute(self) -> Blueprint:
        self.append_log("BlueprintGenerationWorkflow started")
        self.append_log(f"Entity type: {self.type_name}")

        # Step 1: Generate
        blueprint_dict = await self._generate()
        self.append_log(f"Generated: {blueprint_dict['name']} ({len(blueprint_dict.get('attributes', {}))} attrs)")

        # Step 2: Validate (self-reflection)
        passed, issues = await self._validate(blueprint_dict)

        # Step 3: Refine if validation failed
        if not passed:
            self.append_log(f"Validation failed: {issues}")
            blueprint_dict = await self._refine(blueprint_dict, issues)
            self.append_log(f"Refined: {blueprint_dict['name']} ({len(blueprint_dict.get('attributes', {}))} attrs)")

        blueprint_dict['bucket_name'] = self.bucket_name
        self.append_log("BlueprintGenerationWorkflow completed")
        return Blueprint(**blueprint_dict)

    async def _generate(self) -> dict:
        user_prompt = GENERATE_PROMPT.format(
            type_name=self.type_name,
            locate_reason=self.locate_reason,
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text,
        )
        raw = await self.invoke_agent([
            {"role": "system", "content": BLUEPRINT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ])
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return await self.execute_subflow(JsonFixWorkflow, raw)

    def _check_rules(self, blueprint_dict: dict) -> list[str]:
        issues = []
        for name in blueprint_dict.get("attributes", {}):
            parts = name.split("_")
            if "or" in parts:
                issues.append(f"- {name}: contains 'or' joining two words; must be split or simplified")
        return issues

    async def _validate(self, blueprint_dict: dict) -> tuple[bool, str]:
        rule_issues = self._check_rules(blueprint_dict)
        if rule_issues:
            return False, "\n".join(rule_issues)

        blueprint_json = json.dumps(blueprint_dict, ensure_ascii=False, indent=2)
        prompt = VALIDATE_PROMPT.format(blueprint_json=blueprint_json)
        raw = await self.invoke_agent([
            {"role": "system", "content": BLUEPRINT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ])
        raw = raw.strip()
        if raw.startswith("PASS"):
            return True, ""
        issues = raw.replace("FAIL", "").strip()
        return False, issues

    async def _refine(self, blueprint_dict: dict, issues: str) -> dict:
        blueprint_json = json.dumps(blueprint_dict, ensure_ascii=False, indent=2)
        prompt = REFINE_PROMPT.format(
            blueprint_json=blueprint_json,
            issues=issues,
            knowledge_text=self.knowledge_text,
        )
        raw = await self.invoke_agent([
            {"role": "system", "content": BLUEPRINT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ])
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return await self.execute_subflow(JsonFixWorkflow, raw)
