"""
Try to find a matching blueprint for a single entity type from existing blueprints in the database.

This workflow takes one entity type and a bucket name, loads existing blueprints from the database,
then uses LLM to determine if any existing blueprint matches the entity type. This enables blueprint reuse.

Input: entity_type (single dict), bucket_name
Output: list[str] - matched blueprint names (empty list if none matched / needs creation)
"""
import json

from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


MATCH_BLUEPRINT_PROMPT = """Determine if any existing blueprint matches the entity type.

Entity Type: {type_name}
Entity Type Reason: {locate_reason}

Existing Blueprints:
{blueprints_json}

Analyze if any existing blueprint semantically matches this entity type.
Consider:
- Blueprint name and description
- Blueprint attributes
- Whether the entity type can be represented by the blueprint

Output ONLY valid JSON:
{{
  "matched": true/false,
  "blueprint_name": "name of matched blueprint" or null,
  "reason": "why it matches or why no match"
}}

Rules:
- Only match if the blueprint can truly represent this entity type
- Consider semantic similarity, not just exact name matching
- If no good match exists, set matched to false
"""


class BlueprintIdentifyWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.entity_type = {}
        self.bucket_name = ""
        self.existing_blueprints = []

    async def build(self, entity_type: dict, bucket_name: str):
        self.entity_type = entity_type
        self.bucket_name = bucket_name
        return self

    async def execute(self) -> list[str]:
        """
        Returns: list of matched blueprint names (empty list if needs creation)
        """
        type_name = self.entity_type.get('type_name')
        self.append_log(f"BlueprintIdentifyWorkflow started for: {type_name}")
        self.append_log(f"Bucket: {self.bucket_name}")

        # Load existing blueprints from database
        self.existing_blueprints = await KnowledgeAccessor.get_blueprint_list(self.bucket_name)
        self.append_log(f"Loaded {len(self.existing_blueprints)} existing blueprints from database")

        if not self.existing_blueprints:
            self.append_log("No existing blueprints, needs creation")
            return []

        match_result = await self._match_blueprint()

        if match_result['matched']:
            matched_name = match_result['blueprint_name']
            self.append_log(f"Matched: {matched_name}")
            self.append_log(f"Reason: {match_result['reason']}")
            return [matched_name]
        else:
            self.append_log("No match, needs creation")
            self.append_log(f"Reason: {match_result['reason']}")
            return []

    async def _match_blueprint(self) -> dict:
        """
        Use LLM to determine if any existing blueprint matches the entity type.
        Returns: {"matched": bool, "blueprint_name": str | None, "reason": str}
        """
        blueprints_info = []
        for bp in self.existing_blueprints:
            bp_info = {
                "name": bp.name,
                "description": bp.description,
                "attributes": {name: attr.description for name, attr in bp.attributes.items()}
            }
            blueprints_info.append(bp_info)

        prompt = MATCH_BLUEPRINT_PROMPT.format(
            type_name=self.entity_type.get('type_name'),
            locate_reason=self.entity_type.get('locate_reason'),
            blueprints_json=json.dumps(blueprints_info, ensure_ascii=False, indent=2)
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            match_result = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            match_result = await self.execute_subflow(JsonFixWorkflow, raw)

        return match_result