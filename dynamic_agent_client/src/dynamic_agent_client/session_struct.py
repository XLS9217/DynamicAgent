"""Wire models for DA session requests and client messages."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting: str
    reconnect_keep: int = 30
    session_id: str | None = None


class TaskSessionRequest(_SessionRequest):
    """Create or resume an ephemeral task."""
    session_type: Literal["task"] = "task"


class ChatSessionRequest(_SessionRequest):
    """Create or resume a chat with configurable compaction."""
    session_type: Literal["chat"]
    compact_prompt: str | None = Field(default=None, min_length=1)
    soft_limit_count: int = Field(default=512_000, gt=0)
    hard_limit_count: int = Field(default=768_000, gt=0, validate_default=True)

    @field_validator("hard_limit_count")
    @classmethod
    def validate_limits(cls, value, info):
        """Require room between soft and hard limits."""
        if value <= info.data.get("soft_limit_count", 512_000):
            raise ValueError("hard_limit_count must exceed soft_limit_count")
        return value


CreateSessionRequest = TaskSessionRequest | ChatSessionRequest


class ClientInvokeMessage(BaseModel):
    type: Literal["invoke"] = "invoke"
    text: str