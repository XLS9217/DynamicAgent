"""
Match an inbound query against existing blueprints via LLM.
If matched, check if attributes are sufficient; if not, upgrade the blueprint.
If no match, return None so the caller can generate a new one.
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase

MATCH_PROMPT = """Given the user query and a list of existing blueprint schemas, determine which blueprint best matches the query.

User Query: {query}

Existing Blueprints:
{blueprints}

If one of the blueprints is a good match, respond with ONLY its name (e.g. "product_overview").
If none of the blueprints match, respond with ONLY: NONE"""

CHECK_PROMPT = """Given the user query and a matched blueprint, determine if the blueprint has enough attributes to fully answer the query.

User Query: {query}

Blueprint: {blueprint_name}
Description: {blueprint_description}
Current Attributes:
{attributes}

If the current attributes are sufficient, respond with ONLY: YES
If additional attributes are needed, respond with ONLY the missing attributes as valid JSON:
{{"new_attr_name": "description of what this attribute represents", ...}}

Rules:
- Only suggest attributes that are genuinely missing
- Attribute names must be in English, lowercase, using underscores
- Keep descriptions concise"""


class BlueprintMatchingWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.knowledge_accessor = None

    async def build(self, query: str, knowledge_accessor):
        self.query = query
        self.knowledge_accessor = knowledge_accessor
        return self

    async def _find(self, blueprints: list[Blueprint]) -> Blueprint | None:
        self.append_log("Finding best matching blueprint")
        bp_descriptions = "\n".join(
            f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
            for bp in blueprints
        )
        prompt = MATCH_PROMPT.format(query=self.query, blueprints=bp_descriptions)
        raw = await self._language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        answer = raw.strip()
        self.append_log(f"LLM match result: {answer}")

        if answer == "NONE":
            return None

        for bp in blueprints:
            if bp.name == answer:
                self.append_log(f"Matched blueprint: {bp.name}")
                return bp

        self.append_log(f"LLM returned '{answer}' but no blueprint matched by name")
        return None

    async def _check(self, blueprint: Blueprint) -> dict[str, str] | None:
        """Returns new attributes dict if upgrade needed, None if sufficient."""
        self.append_log(f"Checking if blueprint '{blueprint.name}' has enough attributes")
        attrs_text = "\n".join(f"- {k}: {v}" for k, v in blueprint.attributes.items())
        prompt = CHECK_PROMPT.format(
            query=self.query,
            blueprint_name=blueprint.name,
            blueprint_description=blueprint.description,
            attributes=attrs_text
        )
        raw = await self._language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        answer = raw.strip()
        if answer == "YES":
            self.append_log("Blueprint attributes are sufficient")
            return None

        self.append_log("Blueprint needs additional attributes")
        try:
            return json.loads(answer)
        except json.JSONDecodeError:
            return await self.execute_subflow(JsonFixWorkflow, answer)

    async def _upgrade(self, blueprint: Blueprint, new_attributes: dict[str, str]) -> Blueprint:
        self.append_log(f"Upgrading blueprint '{blueprint.name}' with {len(new_attributes)} new attributes")
        merged = {**blueprint.attributes, **new_attributes}
        upgraded = Blueprint(name=blueprint.name, description=blueprint.description, attributes=merged)
        # TODO: persist upgraded blueprint via knowledge_accessor.update_blueprint()
        return upgraded

    async def execute(self) -> Blueprint | None:
        self.append_log("BlueprintMatchingWorkflow started")
        blueprints = self.knowledge_accessor.get_blueprint_list()
        if not blueprints:
            self.append_log("No existing blueprints, returning None")
            return None

        matched = await self._find(blueprints)
        if matched is None:
            self.append_log("No match found")
            return None

        new_attrs = await self._check(matched)
        if new_attrs:
            matched = await self._upgrade(matched, new_attrs)

        self.append_log("BlueprintMatchingWorkflow completed")
        return matched