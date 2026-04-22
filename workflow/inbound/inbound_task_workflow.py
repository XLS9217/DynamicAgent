"""
Inbound task workflow for multi-entity knowledge inbound.

Flow:
1. Detect entities from user query (what types of entities to extract)
2. Match detected entities to existing blueprints or generate new ones
3. Create fill tasks for each entity instance found in the text
"""
import json

from workflow.inbound.blueprint_generation_workflow import BlueprintGenerationWorkflow
from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint


DETECT_PROMPT = """Analyze the user query to determine extraction mode.

User Query: {inbound_query}

Does the user want to extract ONE type of entity or MULTIPLE types of entities?

Output one word: "single" or "multiple"

Examples:
- "record THIS product" → single (one entity type: Product)
- "这个产品" → single (one entity type: Product)
- "find all products and their manufacturers" → multiple (two entity types: Product, Manufacturer)
- "extract people, companies, and locations" → multiple (three entity types)
"""


MATCH_SINGLE_PROMPT = """Analyze the user query and identify ONE entity type to extract.

User Query: {inbound_query}

Knowledge Text (preview):
{knowledge_text}

Existing Blueprints:
{existing_blueprints}

The user wants to extract ONE type of entity.

If an existing blueprint matches, output:
{{"blueprint_name": "Name"}}

If no match, output:
{{"generate_query": "A <Blueprint Name> blueprint, it describes <what kind of entity>, it will have attributes <attr1>, <attr2>, <attr3>"}}

Rules:
- Blueprint name should be generic and represent a category (e.g., "Product", "Document", "Person")
- List attributes from the user query
- Focus on the entity TYPE, not specific instances
"""


MATCH_MULTIPLE_PROMPT = """Analyze the user query and identify all entity types to extract.

User Query: {inbound_query}

Knowledge Text (preview):
{knowledge_text}

Existing Blueprints:
{existing_blueprints}

The user wants to extract MULTIPLE types of entities.

For each entity type:
- If it matches an existing blueprint, add to "blueprint_names"
- If no match, add to "generate_queries"

Output as JSON:
{{
  "blueprint_names": ["Name1", "Name2", ...],
  "generate_queries": ["A <Blueprint Name> blueprint, it describes <what>, it will have attributes <attr1>, <attr2>", ...]
}}

Rules:
- Only return entity TYPES, not instances
- Blueprint names should be generic categories (e.g., "Product", "Person", "Company")
- Do NOT return both blueprint_names and generate_queries for the same entity type
- If no existing blueprints match, only use generate_queries
- List attributes from the user query
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
        Returns: list of {"enriched_query": str, "blueprint": Blueprint}
        """
        self.append_log("InboundTaskWorkflow started")

        # Step 1: Detect mode (single or multiple)
        mode = await self._detect_mode()

        # Step 2: Route to single or multiple matching
        if mode == "single":
            all_blueprints = await self._match_single()
        else:
            all_blueprints = await self._match_multiple()

        # Step 3: Create tasks (skip TASK_PROMPT for single mode)
        if mode == "single":
            tasks = []
            for blueprint in all_blueprints:
                tasks.append({
                    "enriched_query": self.inbound_query,
                    "blueprint": blueprint
                })
            self.append_log(f"Single mode: created {len(tasks)} task(s) directly")
        else:
            tasks = await self._create_tasks(all_blueprints)

        self.append_log(f"Workflow complete: created {len(tasks)} fill tasks")
        return tasks

    async def _detect_mode(self) -> str:
        """
        Determine if user wants single or multiple entity extraction.
        Returns: "single" or "multiple"
        """
        self.append_log("Detecting extraction mode")

        prompt = DETECT_PROMPT.format(inbound_query=self.inbound_query)
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])
        mode = raw.strip().lower().strip('"')

        if mode not in ("single", "multiple"):
            self.append_log(f"Unexpected mode '{mode}', defaulting to multiple")
            mode = "multiple"

        self.append_log(f"Mode: {mode}")
        return mode

    async def _match_single(self) -> list[Blueprint]:
        """
        Match or generate ONE blueprint for single entity extraction.
        Returns: list with one Blueprint
        """
        self.append_log("Matching single blueprint")

        blueprints = await self.knowledge_accessor.get_blueprint_list(self.bucket_name) if self.knowledge_accessor else []

        if not blueprints:
            bp_descriptions = "No existing blueprints"
        else:
            bp_descriptions = "\n".join(
                f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
                for bp in blueprints
            )

        prompt = MATCH_SINGLE_PROMPT.format(
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text[:2000],
            existing_blueprints=bp_descriptions
        )

        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = await self.execute_subflow(JsonFixWorkflow, raw)

        if "blueprint_name" in result:
            name = result["blueprint_name"]
            self.append_log(f"Matched existing blueprint: {name}")
            bp = next((b for b in blueprints if b.name == name), None)
            if bp:
                return [bp]
            self.append_log(f"Blueprint '{name}' not found, falling through to generate")

        if "generate_query" in result:
            self.append_log(f"Generating blueprint: {result['generate_query'][:100]}...")
            generated = await self._generate_blueprints([result["generate_query"]])
            return generated

        self.append_log("No blueprint matched or generated")
        return []

    async def _match_multiple(self) -> list[Blueprint]:
        """
        Match or generate MULTIPLE blueprints for multi-entity extraction.
        Returns: list of Blueprints
        """
        self.append_log("Matching multiple blueprints")

        blueprints = await self.knowledge_accessor.get_blueprint_list(self.bucket_name) if self.knowledge_accessor else []

        if not blueprints:
            bp_descriptions = "No existing blueprints"
        else:
            bp_descriptions = "\n".join(
                f"- {bp.name}: {bp.description} (attributes: {', '.join(bp.attributes.keys())})"
                for bp in blueprints
            )

        prompt = MATCH_MULTIPLE_PROMPT.format(
            inbound_query=self.inbound_query,
            knowledge_text=self.knowledge_text[:2000],
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

            self.append_log(f"Created {len(queries)} tasks for blueprint: {blueprint.name}")
            for i, q in enumerate(queries, 1):
                self.append_log(f"  Task {i}: {q}")

            for query in queries:
                task = {
                    "enriched_query": query,
                    "blueprint": blueprint
                }
                all_tasks.append(task)

        return all_tasks
