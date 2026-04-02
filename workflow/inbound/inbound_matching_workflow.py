"""
Find and optionally upgrade existing blueprints to match a user query.

Two-stage LLM workflow: (1) semantic matching - compares query against all blueprint
names, descriptions, and attributes to find the best match; (2) sufficiency check -
determines if matched blueprint has enough attributes to answer the query. If attributes
are missing, suggests new ones and merges them into the blueprint. Returns None if no
semantic match found, signaling the caller to generate a new blueprint.
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint, BlueprintAttributeSchema
from workflow.utility.json_fix_workflow import JsonFixWorkflow
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
{{"new_attr_name": {{"description": "description of what this attribute represents", "is_identifier": false}}, ...}}

Rules:
- Only suggest attributes that are genuinely missing
- Attribute names must be in English, lowercase, using underscores
- Keep descriptions concise
- Set is_identifier to false for all new attributes (the blueprint already has one identifier)"""


class BlueprintMatchingWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.bucket_name = ""
        self.knowledge_accessor = None

    async def build(self, query: str, bucket_name: str, knowledge_accessor):
        self.query = query
        self.bucket_name = bucket_name
        self.knowledge_accessor = knowledge_accessor
        return self

    async def _find(self, blueprints: list[Blueprint]) -> Blueprint | None:
        self.append_log("Finding best matching blueprint")
        bp_descriptions = "\n".join(
            f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
            for bp in blueprints
        )
        prompt = MATCH_PROMPT.format(query=self.query, blueprints=bp_descriptions)
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])
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

    async def _check(self, blueprint: Blueprint) -> dict[str, BlueprintAttributeSchema] | None:
        """Returns new attributes dict if upgrade needed, None if sufficient."""
        self.append_log(f"Checking if blueprint '{blueprint.name}' has enough attributes")
        attrs_text = "\n".join(f"- {k}: {v.description} (identifier: {v.is_identifier})" for k, v in blueprint.attributes.items())
        prompt = CHECK_PROMPT.format(
            query=self.query,
            blueprint_name=blueprint.name,
            blueprint_description=blueprint.description,
            attributes=attrs_text
        )
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])
        answer = raw.strip()
        if answer == "YES":
            self.append_log("Blueprint attributes are sufficient")
            return None

        self.append_log("Blueprint needs additional attributes")
        try:
            raw_dict = json.loads(answer)
        except json.JSONDecodeError:
            raw_dict = await self.execute_subflow(JsonFixWorkflow, answer)
        return {k: BlueprintAttributeSchema(**v) for k, v in raw_dict.items()}

    async def _upgrade(self, blueprint: Blueprint, new_attributes: dict[str, BlueprintAttributeSchema]) -> Blueprint:
        self.append_log(f"Upgrading blueprint '{blueprint.name}' with {len(new_attributes)} new attributes")
        merged = {**blueprint.attributes, **new_attributes}
        upgraded = Blueprint(name=blueprint.name, description=blueprint.description, attributes=merged)
        # TODO: persist upgraded blueprint via knowledge_accessor.update_blueprint()
        return upgraded

    async def execute(self) -> Blueprint | None:
        self.append_log("BlueprintMatchingWorkflow started")
        blueprints = await self.knowledge_accessor.get_blueprint_list(self.bucket_name)
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