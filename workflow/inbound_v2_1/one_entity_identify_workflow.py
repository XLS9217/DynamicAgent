"""
Identify exactly one primary entity type from inbound query and knowledge text.

This workflow is for single-entity inbound mode. It analyzes the inbound query,
source metadata, and knowledge text, then returns exactly one entity type.

Input:
- inbound_query: User instruction for what to extract/store
- knowledge_text: Source text to ingest
- source_metadata: Optional caller metadata such as meeting_id, title, file name

Output:
dict with {"type_name": str, "locate_reason": str}
"""
import json

from workflow.utility.json_fix_workflow import JsonFixWorkflow
from workflow.workflow_base import WorkflowBase


IDENTIFY_ONE_ENTITY_PROMPT = """Analyze the inbound query and knowledge text, then identify exactly ONE primary entity type to store.

User Query:
{inbound_query}

Source Metadata:
{source_metadata}

Knowledge Text:
{knowledge_text}

Return exactly one entity type.

Output ONLY valid JSON object:
{{
  "type_name": "EntityType",
  "locate_reason": "why this single entity type is the primary target and how it appears in the text"
}}

Rules:
- Return exactly one JSON object, not a list.
- Identify an entity TYPE, not an instance.
- Use singular form, e.g. "Meeting" not "Meetings".
- Prefer the entity type most directly requested by the inbound query.
- If the text is a transcript, notes, report, document, or record about one main thing, choose that main thing as the entity type.
- Do not extract supporting entities such as people, companies, topics, decisions, action items, products, or tools unless the inbound query clearly says one of those is the main target.
- Use source metadata only as context. Do not copy metadata fields into the type name.
- Keep type names generic and reusable.
- The locate_reason must explain why this is the single primary entity type.
"""


class OneEntityIdentifyWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.inbound_query = ""
        self.knowledge_text = ""
        self.source_metadata = None

    async def build(
        self,
        inbound_query: str,
        knowledge_text: str,
        source_metadata: dict | None = None,
    ):
        self.inbound_query = inbound_query
        self.knowledge_text = knowledge_text
        self.source_metadata = source_metadata
        return self

    async def execute(self) -> dict:
        """
        Returns: {"type_name": str, "locate_reason": str}
        """
        self.append_log("OneEntityIdentifyWorkflow started")
        self.append_log(f"Inbound query: {self.inbound_query}")

        entity_type = await self._identify_one_entity_type()

        self.append_log(f"Identified entity type: {entity_type.get('type_name')}")
        self.append_log(f"Reason: {entity_type.get('locate_reason')}")
        self.append_log("OneEntityIdentifyWorkflow completed")
        return entity_type

    async def _identify_one_entity_type(self) -> dict:
        prompt = IDENTIFY_ONE_ENTITY_PROMPT.format(
            inbound_query=self.inbound_query,
            source_metadata=json.dumps(self.source_metadata or {}, ensure_ascii=False, indent=2),
            knowledge_text=self.knowledge_text,
        )
        raw = await self.invoke_agent([{"role": "user", "content": prompt}])

        try:
            entity_type = json.loads(raw)
        except json.JSONDecodeError:
            self.append_log("JSON decode failed, invoking JsonFixWorkflow")
            entity_type = await self.execute_subflow(JsonFixWorkflow, raw)

        if isinstance(entity_type, list):
            self.append_log("Warning: expected one object, got list. Taking first item.")
            entity_type = entity_type[0] if entity_type else {}

        if not isinstance(entity_type, dict):
            self.append_log(f"Warning: expected dict, got {type(entity_type)}. Returning empty fallback.")
            entity_type = {}

        if not entity_type.get("type_name"):
            entity_type["type_name"] = "KnowledgeItem"

        if not entity_type.get("locate_reason"):
            entity_type["locate_reason"] = "Fallback single entity type inferred from inbound single-entity mode."

        return entity_type
