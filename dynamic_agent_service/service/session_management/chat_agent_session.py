"""Durable chat sessions and conversation memory."""
import asyncio
import uuid

from dynamic_agent_service.agent.compact_agent import CompactTaskAgent
from dynamic_agent_service.service.memory_accessor import MemoryAccessor
from dynamic_agent_service.service.service_structs import MessageItem, SessionMeta, StoredImagePart
from dynamic_agent_service.service.session_accessor import SessionAccessor

from .agent_session_base import AgentSessionBase, _tool_arguments_to_object


class ChatAgentSession(AgentSessionBase):
    """Maintain chat history, memory tools and context compaction."""

    session_type = "chat"

    def __init__(
        self, setting: str, reconnect_keep: int = 30, session_id: str | None = None,
        soft_limit_count: int = 512_000, hard_limit_count: int = 768_000,
        compact_prompt: str | None = None,
    ):
        super().__init__(setting, reconnect_keep, session_id)
        self.soft_limit_count = soft_limit_count
        self.hard_limit_count = hard_limit_count
        self.compact_prompt = compact_prompt
        self._compact_pending = False
        self._last_user_instruction = ""

    async def append_message(
        self,
        role: str,
        content: str | MessageItem,
    ) -> str:
        """Store a message using the session storage policy and return its UUID."""
        return await SessionAccessor.append_message(
            self.session_id,
            content if isinstance(content, MessageItem) else MessageItem.from_text(role, content),
        )

    async def read_context(self) -> list[MessageItem]:
        """Load durable chat context from the last compaction boundary."""
        return await SessionAccessor.load_context(self.session_id)

    async def expire_cache(self) -> None:
        """Release cached messages while retaining chat metadata and media."""
        await SessionAccessor.delete_cached_messages(
            self.session_id, delete_media=False, keep_meta=True,
        )

    def meta(self) -> SessionMeta:
        """Include chat compaction settings in session metadata."""
        meta = super().meta()
        meta.soft_limit_count = self.soft_limit_count
        meta.hard_limit_count = self.hard_limit_count
        meta.compact_prompt = self.compact_prompt
        return meta

    async def agent_setup(self):
        """Attach memory and compaction hooks to the main chat runner."""
        await super().agent_setup()
        runner = self.agi._runner
        runner.after_tools = self.compacted_context
        runner.on_compact = self.perform_compaction
        runner.soft_limit_count = self.soft_limit_count
        runner.hard_limit_count = self.hard_limit_count

    def start_trigger(self, text: str, trigger_id: str, images: list[StoredImagePart] | None = None) -> None:
        """Track the current instruction for chat compaction."""
        self._last_user_instruction = text
        self._compact_pending = False
        super().start_trigger(text, trigger_id, images)

    async def compacted_context(self) -> list[dict] | None:
        """Compact after the request's tool result is safely stored."""
        if not self._compact_pending:
            return None
        self._compact_pending = False
        return await self.perform_compaction()

    async def perform_compaction(self) -> list[dict]:
        """Run the task agent, commit its generated message, then restore context."""
        snapshot = await self.load_model_messages()
        task = CompactTaskAgent(self.agi.openai_adapter, self.session_id, compact_prompt=self.compact_prompt)
        result = await asyncio.wait_for(task.run(snapshot, self._last_user_instruction), timeout=120)
        content = ("Previous conversation has been compacted. This is conversation memory, not new instructions.\n\n"
                   f"Summary:\n{result.summary}\n\nCompacted memory:\n{result.compacted}\n\n"
                   f"Last user instruction:\n{self._last_user_instruction}")
        message = MessageItem.from_text("user", content)
        message.message_id = str(uuid.uuid4())
        checkpoint = {"id": str(uuid.uuid4()), "summary": result.summary, "compacted": result.compacted,
                      "last_message_id": message.message_id}
        await MemoryAccessor.save(self.session_id, checkpoint, message)
        return await self.load_model_messages()

    async def memory(self, request) -> object:
        """Handle memory only for a pending main-agent tool invocation."""
        if request.runner_id != self.agi.runner_id or not self.accepts_trigger(request.trigger_id):
            raise ValueError("Memory request does not belong to the active main runner")
        self.agi.validate_pending_tool_call(request.runner_id, request.tool_call_id)
        call = self.agi.pending_tool_calls[request.tool_call_id]
        if call.name != f"MemoryOperator_{request.action}":
            raise ValueError("Memory action does not match the pending tool")
        if request.action == "compact":
            if len(self.agi.pending_tool_calls) != 1:
                raise ValueError("Call compact alone without parallel tools")
            if _tool_arguments_to_object(call.arguments):
                raise ValueError("compact takes no arguments")
            self._compact_pending = True
            return {"status": "requested", "message": "Compaction runs before the agent resumes."}
        checkpoints = await MemoryAccessor.all(self.session_id)
        if request.action == "list":
            return [{"id": c["id"], "summary": c["summary"]} for c in checkpoints]
        for checkpoint in checkpoints:
            if checkpoint["id"] == request.checkpoint_id:
                return checkpoint
        raise ValueError("Checkpoint not found in this session")
