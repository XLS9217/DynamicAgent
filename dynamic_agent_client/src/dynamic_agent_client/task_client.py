"""Task client for sessions with process-local history."""
from typing import Self

from .session_struct import TaskSessionRequest
from .client import DynamicAgentClient


class DynamicAgentTaskClient(DynamicAgentClient):
    """Run tasks with ephemeral session history."""

    @classmethod
    async def create(
        cls,
        setting: str,
        reconnect_keep: int = 30,
        session_id: str | None = None,
    ) -> Self:
        """Create or resume a task session."""
        return await cls._open(TaskSessionRequest(
            setting=setting,
            session_type="task",
            reconnect_keep=reconnect_keep,
            session_id=session_id,
        ))
