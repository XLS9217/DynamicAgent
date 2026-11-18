from pathlib import Path
from uuid import UUID
from typing import Callable, Self

from .client import DynamicAgentClient
from .service_handler import ServiceHandler
from .client_struct import AgentEvent, AgentResponseChunk


class DynamicAgentChatClient(DynamicAgentClient):
    """Dynamic Agent client with durable PostgreSQL chat history."""

    @classmethod
    async def connect(cls, server_addr: str):
        return await super().connect(server_addr)

    @classmethod
    async def create(
        cls,
        setting: str,
        reconnect_keep: int = 30,
        session_id: str = None,
        soft_limit_count: int = 512_000,
        hard_limit_count: int = 768_000,
        compact_prompt: str | None = None,
    ) -> Self:
        return await super().create(
            setting=setting,
            session_type="chat",
            reconnect_keep=reconnect_keep,
            session_id=session_id,
            soft_limit_count=soft_limit_count,
            hard_limit_count=hard_limit_count,
            compact_prompt=compact_prompt,
        )

    async def history(self, *, history_secret: str, offset: int = 0, limit: int = 50) -> dict:
        """Read current saved context for this connected chat session."""
        if not history_secret or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Require history authorization, offset >= 0 and limit 1..100")
        if self.session_id is None:
            raise ValueError("Connect to a chat session before reading history")
        return await ServiceHandler.chat_history(str(UUID(self.session_id)), history_secret=history_secret, offset=offset, limit=limit)

    async def trigger(
        self,
        text: str,
        on_chunk: Callable[[AgentResponseChunk], None] = None,
        on_event: Callable[[AgentEvent], None] = None,
        images: list[str | Path] | None = None,
    ):
        return await super().trigger(text, on_chunk, on_event, images)

    async def stop(self) -> None:
        return await super().stop()

    async def add_operator(self, operator):
        return await super().add_operator(operator)

    @classmethod
    async def delete_session(cls, session_id: str) -> bool:
        return await super().delete_session(session_id)

    async def close(self):
        return await super().close()
