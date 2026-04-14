"""
Inbound task workflow for multi-entity knowledge inbound.

Single-stage process:
Match blueprints: identify entity types and return blueprint names and generation queries

Returns:
- blueprint_names: list of matched blueprint names
- generate_queries: list of queries for generating new blueprints
"""
import json

from workflow.inbound.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint


MATCH_PROMPT = """Analyze the text and identify all entity types based on the user query.

User Query: {inbound_query}

---

Knowledge Text:
{knowledge_text}

---

Existing Blueprints:
{existing_blueprints}

For each entity type you identify:
- If it matches an existing blueprint, add the blueprint name to "blueprint_names"
- If no match exists, add a description to "generate_queries" in this format:
  "A <Blueprint Name> blueprint, it is about <description>, it will have attributes <attr1>, <attr2>, <attr3>"

Output as JSON:
{{
  "blueprint_names": ["Name", "AnotherName", ...],
  "generate_queries": ["A blueprint for Entity, it is about...", "A blueprint for AnotherEntity, it is about...", ...]
}}

Rules:
- Only include entities relevant to the user query, use wording inside user query if possible
- blueprint_names should contain existing blueprint names that match
- generate_queries should follow the exact format: "A <BlueprintName> blueprint, it is about <description>, it will have attributes <list>"
- Blueprint names should be human-readable with proper capitalization (e.g., "Entity", "AnotherEntity"...)
- List all necessary attributes that would be needed for each entity type, based on user's query
"""


TASK_PROMPT = """Identify all individual entities in the text that match this blueprint type.

Blueprint: {blueprint_name}
Description: {blueprint_description}
Attributes: {attributes}

Knowledge Text:
{knowledge_text}

For each individual entity instance you find, create a focused extraction query.

Output as JSON list:
[
  "Extract information about <specific entity 1>",
  "Extract information about <specific entity 2>",
  ...
]

Rules:
- Each query should target ONE specific entity instance
- Be specific about which entity to extract (use names, identifiers from the text)
- Only include entities that actually exist in the text
"""


class InboundTaskWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.knowledge_text = ""
        self.inbound_query = ""
        self.bucket_name = ""
        self.knowledge_accessor = None

    async def build(self, knowledge_text: str, inbound_query: str, bucket_name: str, knowledge_accessor):
        self.knowledge_text = knowledge_text
        self.inbound_query = inbound_query
        self.bucket_name = bucket_name
        self.knowledge_accessor = knowledge_accessor
        return self

    async def execute(self) -> list[dict]:
        """
        Returns: list of {"enriched_query": str, "blueprint": Blueprint, "knowledge_text": str}
        """
        self.append_log("InboundTaskWorkflow started")

        result = await self._match_blueprints()

        all_blueprints = []

        if result['blueprint_names']:
            matched = await self.knowledge_accessor.get_blueprint_list(self.bucket_name)
            for name in result['blueprint_names']:
                bp = next((b for b in matched if b.name == name), None)
                if bp:
                    all_blueprints.append(bp)

        if result['generate_queries']:
            self.append_log(f"Generating {len(result['generate_queries'])} new blueprints")
            generated = await self._generate_blueprints(result['generate_queries'])
            all_blueprints.extend(generated)

        tasks = await self._create_tasks(all_blueprints)

        self.append_log(f"Workflow complete: created {len(tasks)} fill tasks")
        return tasks

    async def _match_blueprints(self) -> dict:
        """
        Identify entity types and match/generate blueprints
        Returns: {"blueprint_names": [...], "generate_queries": [...]}
        """
        self.append_log("Matching/generating blueprints")

        blueprints = await self.knowledge_accessor.get_blueprint_list(self.bucket_name) if self.knowledge_accessor else []

        if not blueprints:
            bp_descriptions = "No existing blueprints"
        else:
            bp_descriptions = "\n".join(
                f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
                for bp in blueprints
            )

        prompt = MATCH_PROMPT.format(
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text,
            existing_blueprints=bp_descriptions
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        self.append_log(f"Matched {len(result.get('blueprint_names', []))} blueprints, need to generate {len(result.get('generate_queries', []))}")
        return result

    async def _generate_blueprints(self, generate_queries: list[str]) -> list[Blueprint]:
        """
        Generate new blueprints from queries and persist them
        Returns: list of generated Blueprint objects
        """
        generated = []
        for query in generate_queries:
            self.append_log(f"Generating blueprint from: {query}")
            blueprint = await self.execute_subflow(
                BlueprintGenerationWorkflow,
                query,
                self.bucket_name,
                self.knowledge_text
            )
            if self.knowledge_accessor:
                blueprint.id = await self.knowledge_accessor.create_blueprint(blueprint)
                self.append_log(f"Persisted blueprint: {blueprint.name} (id={blueprint.id})")
            generated.append(blueprint)
        return generated

    async def _create_tasks(self, blueprints: list[Blueprint]) -> list[dict]:
        """
        Create fill tasks for each entity instance found in the text.
        Returns: list of {"enriched_query": str, "blueprint": Blueprint}
        """
        self.append_log(f"Creating tasks for {len(blueprints)} blueprints")

        all_tasks = []
        for blueprint in blueprints:
            self.append_log(f"Identifying entities for blueprint: {blueprint.name}")

            attributes_text = ", ".join(blueprint.attributes.keys())
            prompt = TASK_PROMPT.format(
                blueprint_name=blueprint.name,
                blueprint_description=blueprint.description,
                attributes=attributes_text,
                knowledge_text=self.knowledge_text
            )

            raw = await self.invoke_agent([{"role": "user", "content": prompt}])

            try:
                queries = json.loads(raw)
            except json.JSONDecodeError:
                queries = await self.execute_subflow(JsonFixWorkflow, raw)

            for query in queries:
                task = {
                    "enriched_query": query,
                    "blueprint": blueprint
                }
                all_tasks.append(task)

            self.append_log(f"Created {len(queries)} tasks for blueprint: {blueprint.name}")

        return all_tasks
