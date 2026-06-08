from typing import Literal, Optional
from pydantic import BaseModel

from dynamic_agent_service.agent.agent_structs import AgentToolCall


class CreateSessionRequest(BaseModel):
    # Session
    setting: str
    webhook_port: int
    reconnect_keep: int = 30
    # Agent
    messages: list = []
    bucket_name: Optional[str] = None


class AgentResponseChunk(BaseModel):
    """
    text stream response
    """
    type: Literal["agent_chunk"]
    text: str
    tool_call: Optional[AgentToolCall] = None
    finished: bool = False
    invoked: bool = False

class ToolExecuteResult(BaseModel):
    type: Literal["tool_execute_result"]
    tool_call_id: str
    content: str

class RagContext(BaseModel):
    """
    RAG-retrieved knowledge surfaced to the client before the agent responds.
    """
    type: Literal["rag_context"]
    knowledge: list[dict]