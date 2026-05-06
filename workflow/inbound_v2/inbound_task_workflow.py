"""
Inbound task workflow for knowledge inbound (v2).

Flow:
1. Retrieve all entities from the text (extract entity instances first)
2. Try to find matching blueprints for these entities
3. For each blueprint, pair it with relevant entities
4. Create fill tasks
"""
import json

from workflow.inbound_v2.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint


RETRIEVE_ENTITIES_PROMPT = """Extract all entity instances from the knowledge text based on the user query.

User Query: {inbound_query}

Knowledge Text:
{knowledge_text}

Identify and list all individual entities mentioned in the text. For each entity, provide:
1. Entity name (identifier)
2. Description of how it exists in the text

Output as JSON list:
[
  {{
    "name": "entity name or identifier",
    "description": "brief description of how this entity exists in the text"
  }},
  ...
]

Rules:
- Extract ALL entity instances, not just types
- Be specific about each individual entity
- Keep descriptions simple and focused on what's in the text
"""


MATCH_BLUEPRINTS_PROMPT = """Based on the retrieved entities, find matching blueprints or determine which new blueprints to create.

User Query: {inbound_query}

Retrieved Entities:
{entities}

Existing Blueprints:
{existing_blueprints}

For each entity type found:
- If an existing blueprint matches, add to "blueprint_names"
- If no match, add to "generate_queries"

Output as JSON:
{{
  "blueprint_names": ["Name1", "Name2", ...],
  "generate_queries": ["A <Blueprint Name> blueprint, it describes <what>, it will have attributes <attr1>, <attr2>", ...]
}}

Rules:
- Match entity types to blueprint types
- Blueprint names should be generic categories (e.g., "Product", "Person", "Company")
- Do NOT return both blueprint_names and generate_queries for the same entity type
- List attributes based on what was found in the entities
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
        Returns: list of {"enriched_query": str, "blueprint": Blueprint, "entities": list}
        """
        self.append_log("InboundTaskWorkflow started")

        # Step 1: Retrieve all entities from the text
        entities = await self._retrieve_entities()

        # Step 2: Match blueprints based on retrieved entities
        all_blueprints = await self._match_blueprints(entities)

        # Step 3: Create tasks by pairing blueprints with relevant entities
        tasks = await self._create_tasks(all_blueprints, entities)

        self.append_log(f"Workflow complete: created {len(tasks)} fill tasks")
        return tasks

    async def _retrieve_entities(self) -> list[dict]:
        """
        Retrieve all entity instances from the knowledge text.
        Returns: list of {"name": str, "description": str}
        """
        self.append_log("Retrieving entities from text")

        prompt = RETRIEVE_ENTITIES_PROMPT.format(
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            entities = json.loads(raw)
        except json.JSONDecodeError:
            entities = await self.execute_subflow(JsonFixWorkflow, raw)

        self.append_log(f"Retrieved {len(entities)} entities")
        for i, entity in enumerate(entities, 1):
            self.append_log(f"  Entity {i}: {entity.get('name')}")

        return entities

    async def _match_blueprints(self, entities: list[dict]) -> list[Blueprint]:
        """
        Match or generate blueprints based on retrieved entities.
        Returns: list of Blueprints
        """
        self.append_log("Matching blueprints based on entities")

        blueprints = await self.knowledge_accessor.get_blueprint_list(self.bucket_name) if self.knowledge_accessor else []

        if not blueprints:
            bp_descriptions = "No existing blueprints"
        else:
            bp_descriptions = "\n".join(
                f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
                for bp in blueprints
            )

        entities_text = json.dumps(entities, ensure_ascii=False, indent=2)

        prompt = MATCH_BLUEPRINTS_PROMPT.format(
            inbound_query=self.inbound_query,
            entities=entities_text,
            existing_blueprints=bp_descriptions
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        all_blueprints = []

        if result.get('blueprint_names'):
            self.append_log(f"Matched: {', '.join(result['blueprint_names'])}")
            for name in result['blueprint_names']:
                bp = next((b for b in blueprints if b.name == name), None)
                if bp:
                    all_blueprints.append(bp)

        if result.get('generate_queries'):
            self.append_log(f"Generating {len(result['generate_queries'])} new blueprints")
            for q in result['generate_queries']:
                self.append_log(f"  Generate: {q[:100]}...")
            generated = await self._generate_blueprints(result['generate_queries'])
            all_blueprints.extend(generated)

        return all_blueprints

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

    async def _create_tasks(self, blueprints: list[Blueprint], entities: list[dict]) -> list[dict]:
        """
        Create fill tasks by pairing blueprints with relevant entities.
        Returns: list of {"enriched_query": str, "blueprint": Blueprint, "entities": list}
        """
        self.append_log(f"Creating tasks for {len(blueprints)} blueprints with {len(entities)} entities")

        all_tasks = []

        # Create one task per entity per blueprint
        # The LLM will determine during filling which entities match which blueprint
        for blueprint in blueprints:
            for entity in entities:
                enriched_query = f"Extract information about {entity.get('name')}"
                task = {
                    "enriched_query": enriched_query,
                    "blueprint": blueprint,
                    "entities": [entity]
                }
                all_tasks.append(task)
                self.append_log(f"  Task: {enriched_query} for blueprint {blueprint.name}")

        return all_tasks
