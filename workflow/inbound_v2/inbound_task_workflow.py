"""
Inbound task workflow for knowledge inbound (v2).

Flow:
1. Locate entity types from the inbound query
2. Try to find existing blueprints for each type, or create new ones
3. For each blueprint, create one fill task that extracts all matching entities from knowledge text
"""
import json

from workflow.inbound_v2.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint


LOCATE_ENTITY_TYPES_PROMPT = """Analyze the inbound query and identify what entity types the user wants to extract.

User Query: {inbound_query}

Identify the entity types mentioned in the query. For each type, provide:
1. Type name (e.g., "Product", "Exploit", "Person", "Company")
2. Brief description of what this type represents

Output as JSON list:
[
  {{
    "type_name": "EntityType",
    "description": "what this type represents"
  }},
  ...
]

Rules:
- Extract entity TYPES, not instances
- Use singular form (e.g., "Product" not "Products")
- Keep type names generic and reusable
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
        Returns: list of {"enriched_query": str, "blueprint": Blueprint}
        """
        self.append_log("InboundTaskWorkflow started")

        # Step 1: Locate entity types from the inbound query
        entity_types = await self._locate_entity_types()

        # Step 2: Find or create blueprints for each entity type
        all_blueprints = await self._find_or_create_blueprints(entity_types)

        # Step 3: Create one fill task per blueprint
        # Each task will extract all matching entities from knowledge text
        tasks = self._create_tasks(all_blueprints)

        self.append_log(f"Workflow complete: created {len(tasks)} fill tasks")
        return tasks

    async def _locate_entity_types(self) -> list[dict]:
        """
        Locate entity types from the inbound query.
        Returns: list of {"type_name": str, "description": str}
        """
        self.append_log("Locating entity types from query")

        prompt = LOCATE_ENTITY_TYPES_PROMPT.format(inbound_query=self.inbound_query)
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            entity_types = json.loads(raw)
        except json.JSONDecodeError:
            entity_types = await self.execute_subflow(JsonFixWorkflow, raw)

        self.append_log(f"Located {len(entity_types)} entity types")
        for i, et in enumerate(entity_types, 1):
            self.append_log(f"  Type {i}: {et.get('type_name')}")

        return entity_types

    async def _find_or_create_blueprints(self, entity_types: list[dict]) -> list[Blueprint]:
        """
        For each entity type, try to find existing blueprint or create new one.
        Returns: list of Blueprints
        """
        self.append_log(f"Finding or creating blueprints for {len(entity_types)} entity types")

        existing_blueprints = await self.knowledge_accessor.get_blueprint_list(self.bucket_name) if self.knowledge_accessor else []
        all_blueprints = []

        for entity_type in entity_types:
            type_name = entity_type.get('type_name')
            self.append_log(f"Processing entity type: {type_name}")

            # Try to find existing blueprint
            matched_bp = None
            for bp in existing_blueprints:
                if bp.name.lower() == type_name.lower():
                    matched_bp = bp
                    break

            if matched_bp:
                self.append_log(f"  Found existing blueprint: {matched_bp.name}")
                all_blueprints.append(matched_bp)
            else:
                # Create new blueprint
                self.append_log(f"  Creating new blueprint for: {type_name}")
                generate_query = f"A {type_name} blueprint, it describes {entity_type.get('description')}"
                blueprint = await self.execute_subflow(
                    BlueprintGenerationWorkflow,
                    generate_query,
                    self.bucket_name,
                    self.knowledge_text
                )
                if self.knowledge_accessor:
                    blueprint.id = await self.knowledge_accessor.create_blueprint(blueprint)
                    self.append_log(f"  Persisted blueprint: {blueprint.name} (id={blueprint.id})")
                all_blueprints.append(blueprint)

        return all_blueprints

    def _create_tasks(self, blueprints: list[Blueprint]) -> list[dict]:
        """
        Create one fill task per blueprint.
        Each task will extract all matching entities from knowledge text.
        Returns: list of {"enriched_query": str, "blueprint": Blueprint}
        """
        self.append_log(f"Creating {len(blueprints)} fill tasks")

        all_tasks = []

        for blueprint in blueprints:
            enriched_query = f"Extract all {blueprint.name} instances from the knowledge text. For each instance, fill available attributes. If an attribute doesn't exist in the text, leave it unfilled."
            task = {
                "enriched_query": enriched_query,
                "blueprint": blueprint
            }
            all_tasks.append(task)
            self.append_log(f"  Task: Extract {blueprint.name} instances")

        return all_tasks