from pathlib import Path
from typing import Callable, Self

from .client import DynamicAgentClient
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
    ) -> Self:
        return await super().create(
            setting=setting,
            session_type="chat",
            reconnect_keep=reconnect_keep,
            session_id=session_id,
        )

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
