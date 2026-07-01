from typing import Literal, Optional
from pydantic import BaseModel

from dynamic_agent_service.agent.agent_structs import AgentToolCall


class CreateSessionRequest(BaseModel):
    # Session
    setting: str
    reconnect_keep: int = 30
    session_id: Optional[str] = None  # provided to resume an existing session


class AgentResponseChunk(BaseModel):
    """
    text stream response
    """
    type: Literal["agent_chunk"]
    text: str
    tool_call: Optional[AgentToolCall] = None
    finished: bool = False
    invoked: bool = False

class ToolResultRequest(BaseModel):
    session_id: str
    tool_call_id: str
    ok: bool = True
    result: object


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
