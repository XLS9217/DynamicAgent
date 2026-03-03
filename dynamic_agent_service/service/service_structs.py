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
    compact_limit: int = None
    compact_target: int = None


class AgentResponseChunk(BaseModel):
    """
    text stream response
    """
    type: Literal["agent_chunk"]
    text: str
    tool_call: Optional[AgentToolCall] = None
    finished: bool = False
    invoked: bool = False
    compacting: Optional[bool] = None # Three state None True False

class ToolExecuteResult(BaseModel):
    type: Literal["tool_execute_result"]
    tool_call_id: str
    content: str