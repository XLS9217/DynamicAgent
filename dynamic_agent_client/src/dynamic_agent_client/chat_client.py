"""Chat client for sessions with durable PostgreSQL history."""
from typing import Self
from uuid import UUID

from .session_struct import ChatSessionRequest
from .client import DynamicAgentClient
from .operator.memory_operator import MemoryOperator
from .service_handler import ServiceHandler


class DynamicAgentChatClient(DynamicAgentClient):
    """Run conversations with persistent history and memory tools."""

    @classmethod
    async def create(
        cls,
        setting: str,
        reconnect_keep: int = 30,
        session_id: str | None = None,
        soft_limit_count: int = 512_000,
        hard_limit_count: int = 768_000,
        compact_prompt: str | None = None,
    ) -> Self:
        """Create or resume a chat session and register its memory tools."""
        client = await cls._open(ChatSessionRequest(
            setting=setting,
            session_type="chat",
            reconnect_keep=reconnect_keep,
            session_id=session_id,
            soft_limit_count=soft_limit_count,
            hard_limit_count=hard_limit_count,
            compact_prompt=compact_prompt,
        ))
        await client.add_operator(MemoryOperator())
        return client

    async def history(self, *, history_secret: str, offset: int = 0, limit: int = 50) -> dict:
        """Read current saved context for this connected chat session."""
        if not history_secret or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Require history authorization, offset >= 0 and limit 1..100")
        if self.session_id is None:
            raise ValueError("Connect to a chat session before reading history")
        return await ServiceHandler.chat_history(str(UUID(self.session_id)), history_secret=history_secret, offset=offset, limit=limit)
