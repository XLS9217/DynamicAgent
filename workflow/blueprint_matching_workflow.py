"""
Match an inbound query against existing blueprints via LLM, or signal that none match.
"""
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint
from workflow.workflow_base import WorkflowBase

MATCH_PROMPT = """Given the user query and a list of existing blueprint schemas, determine which blueprint best matches the query.

User Query: {query}

Existing Blueprints:
{blueprints}

If one of the blueprints is a good match, respond with ONLY its name (e.g. "product_overview").
If none of the blueprints match, respond with ONLY: NONE"""


class BlueprintMatchingWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.knowledge_accessor = None

    async def build(self, query: str, knowledge_accessor):
        self.query = query
        self.knowledge_accessor = knowledge_accessor
        return self

    async def execute(self) -> Blueprint | None:
        self._append_log("BlueprintMatchingWorkflow started")
        blueprints = self.knowledge_accessor.get_blueprint_list()
        if not blueprints:
            self._append_log("No existing blueprints, returning None")
            return None

        bp_descriptions = "\n".join(
            f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
            for bp in blueprints
        )
        prompt = MATCH_PROMPT.format(query=self.query, blueprints=bp_descriptions)
        raw = await self._language_engine.async_get_response(
            [{"role": "user", "content": prompt}]
        )
        answer = raw.strip()
        self._append_log(f"LLM match result: {answer}")

        if answer == "NONE":
            return None

        for bp in blueprints:
            if bp.name == answer:
                self._append_log(f"Matched blueprint: {bp.name}")
                return bp

        self._append_log(f"LLM returned '{answer}' but no blueprint matched by name, returning None")
        return None