from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

from dynamic_agent_service.agent.agent_structs import AgentToolCall


class CreateSessionRequest(BaseModel):
    # Session
    setting: str
    reconnect_keep: int = 30
    session_id: Optional[str] = None  # provided to resume an existing session
    persist: bool = False


class AgentResponseChunk(BaseModel):
    """
    text stream response
    """
    type: Literal["agent_chunk"]
    text: str
    tool_call: Optional[AgentToolCall] = None
    finished: bool = False
    invoked: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    runner_id: str | None = None
    runner_name: str | None = None
    parent_runner_id: str | None = None
    parent_tool_call_id: str | None = None

class ToolResultRequest(BaseModel):
    session_id: str
    runner_id: Optional[str] = None
    tool_call_id: str
    ok: bool = True
    result: object


class InitSubagentRequest(BaseModel):
    session_id: str
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
#   session:{session_id}:rag       -> RagCache (JSON)

class SessionMeta(BaseModel):
    """Core session metadata. Stored at session:{session_id}:meta."""
    session_id: str
    setting: str
    reconnect_keep: int
    bucket_name: Optional[str] = None
    created_at: float  # Unix timestamp
    disconnect_time: Optional[float] = None  # set when WebSocket disconnects


class MessageItem(BaseModel):
    """One conversation message. Each element of session:{session_id}:messages."""
    role: str  # "system" | "user" | "assistant"
    content: str


class RagCache(BaseModel):
    """Last RAG-retrieved knowledge. Stored at session:{session_id}:rag."""
    query: str
    knowledge: list[dict]  # reconstructed instances (heterogeneous attribute dicts)
    retrieved_at: float  # Unix timestamp
