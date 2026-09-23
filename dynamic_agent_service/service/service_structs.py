from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from dynamic_agent_client.client_struct import AgentResponseChunk


class CreateSessionRequest(BaseModel):
    # Session
    setting: str
    reconnect_keep: int = 30
    session_id: Optional[str] = None  # provided to resume an existing session


class ToolResultRequest(BaseModel):
    session_id: str
    trigger_id: str | None = None
    runner_id: Optional[str] = None
    tool_call_id: str
    ok: bool = True
    result: object


class InitSubagentRequest(BaseModel):
    session_id: str
    trigger_id: str | None = None
    parent_runner_id: str
    name: str
    setting: str
    operators: list[dict] = Field(min_length=1)

    @field_validator(
        "session_id",
        "parent_runner_id",
        "name",
        "setting",
    )
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value


class TriggerSubagentRequest(BaseModel):
    session_id: str
    trigger_id: str | None = None
    parent_runner_id: str
    parent_tool_call_id: str
    runner_id: str
    task: str

    @field_validator(
        "session_id",
        "parent_runner_id",
        "parent_tool_call_id",
        "runner_id",
        "task",
    )
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value


# ===== Redis-backed session state =====
# Keys:
#   session:{session_id}:meta      -> SessionMeta (JSON)
#   session:{session_id}:messages  -> Redis list of MessageItem (JSON)

class SessionMeta(BaseModel):
    """Core session metadata. Stored at session:{session_id}:meta."""
    session_id: str
    setting: str
    reconnect_keep: int
    created_at: float  # Unix timestamp
    disconnect_time: Optional[float] = None  # set when WebSocket disconnects


class TextPart(BaseModel):
    """Store one text segment in its original position."""

    type: Literal["text"] = "text"
    text: str


class StoredImagePart(BaseModel):
    """Reference one validated image below MEDIA_DIR."""

    type: Literal["image"] = "image"
    media_id: UUID
    relative_path: str
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detail: Literal["auto", "low", "high"] = "auto"


MessagePart = Annotated[TextPart | StoredImagePart, Field(discriminator="type")]


class MessageItem(BaseModel):
    """Store one versioned conversation message in PostgreSQL and Redis."""

    version: Literal[1] = 1
    role: Literal["system", "user", "assistant", "tool"]
    parts: list[MessagePart] = Field(min_length=1)

    @classmethod
    def from_text(cls, role: str, text: str) -> "MessageItem":
        """Build a text-only message."""
        return cls(role=role, parts=[TextPart(text=text)])

    @classmethod
    def from_user(
        cls,
        text: str,
        images: list[StoredImagePart] | None = None,
    ) -> "MessageItem":
        """Build one user message while preserving text-before-image order."""
        parts: list[MessagePart] = []
        if text:
            parts.append(TextPart(text=text))
        parts.extend(images or [])
        if not parts:
            raise ValueError("A trigger requires text or at least one image")
        return cls(role="user", parts=parts)

    def public_message(self) -> dict:
        """Return history without exposing server filesystem paths or hashes."""
        if len(self.parts) == 1 and isinstance(self.parts[0], TextPart):
            return {"role": self.role, "content": self.parts[0].text}
        content = []
        for part in self.parts:
            if isinstance(part, TextPart):
                content.append(part.model_dump())
            else:
                content.append({
                    "type": "image",
                    "media_id": str(part.media_id),
                    "mime_type": part.mime_type,
                    "byte_size": part.byte_size,
                    "detail": part.detail,
                })
        return {"role": self.role, "content": content}
