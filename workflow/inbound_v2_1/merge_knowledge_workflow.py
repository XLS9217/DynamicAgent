"""
Merge a new filled instance with an existing collided instance.

This workflow is intentionally not wired into the inbound orchestrator yet. It
prepares the conflict-resolution behavior needed after collision detection by
asking the agent to merge existing and incoming attribute values without
inventing information.
"""
import json

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


MERGE_SYSTEM_PROMPT = """You are a knowledge merge agent.

You merge two descriptions of the same real-world entity into one clean filled instance.

Rules:
- Preserve useful information from both the existing instance and the incoming instance.
- Do not invent facts that are not present in either input.
- Prefer the more specific, complete, and clearly sourced wording when values conflict.
- If both values are complementary, combine them into a concise unified value.
- Keep the identifier stable. Use the existing identifier unless the incoming identifier is clearly a more complete name for the same entity.
- Keep all output keys aligned to the blueprint attributes plus summary when present.
- Output only valid JSON.
"""


MERGE_USER_PROMPT = """Blueprint:
{blueprint_json}

Existing stored instance:
{existing_instance_json}

Incoming filled instance:
{incoming_instance_json}

Collision reason:
{collision_reason}

Merge the existing and incoming instances into one filled instance.

Output ONLY valid JSON:
{{
  "attribute_name": "merged value",
  ...
}}
"""


class MergeKnowledgeWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.blueprint = None
        self.existing_instance = {}
        self.incoming_instance = {}
        self.collision = {}

    async def build(
        self,
        blueprint: Blueprint,
        existing_instance: dict,
        incoming_instance: dict,
        collision: dict | None = None,
    ):
        self.blueprint = blueprint
        self.existing_instance = existing_instance
        self.incoming_instance = incoming_instance
        self.collision = collision or {}
        return self

    async def execute(self) -> dict:
        """
        Returns a merged filled instance dict.

        This workflow only computes the merged values. It does not update
        Postgres or Milvus; persistence should be handled by the caller when
        this workflow is eventually wired into collision handling.
        """
        self.append_log("MergeKnowledgeWorkflow started")
        self.append_log(f"Blueprint: {self.blueprint.name}")
        self.append_log(f"Collision reason: {self.collision.get('reason', '')}")

        merged = await self._merge()
        merged = {k: v for k, v in merged.items() if v is not None}

        self.append_log(f"Merged {len(merged)} attributes")
        self.append_log("MergeKnowledgeWorkflow completed")
        return merged

    async def _merge(self) -> dict:
        blueprint_json = json.dumps(self._blueprint_payload(), ensure_ascii=False, indent=2)
        existing_json = json.dumps(self.existing_instance, ensure_ascii=False, indent=2)
        incoming_json = json.dumps(self.incoming_instance, ensure_ascii=False, indent=2)

        prompt = MERGE_USER_PROMPT.format(
            blueprint_json=blueprint_json,
            existing_instance_json=existing_json,
            incoming_instance_json=incoming_json,
            collision_reason=self.collision.get("reason", ""),
        )

        raw = await self.invoke_agent([
            {"role": "system", "content": MERGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            return await self.execute_subflow(JsonFixWorkflow, raw)

    def _blueprint_payload(self) -> dict:
        return {
            "name": self.blueprint.name,
            "description": self.blueprint.description,
            "attributes": {
                name: {
                    "description": attr.description,
                    "is_identifier": attr.is_identifier,
                }
                for name, attr in self.blueprint.attributes.items()
            },
        }
