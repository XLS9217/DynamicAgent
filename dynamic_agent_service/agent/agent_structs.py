from enum import StrEnum

from pydantic import BaseModel


class AgentState(StrEnum):
    """Lifecycle states for an agent invocation."""

    IDLE = "idle"
    RUNNING = "running"
    GATHERING = "gathering_tool_result"


class AgentToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # this must be json string


class AgentInvokeResult(BaseModel):
    full_text: str
    tool_calls: list[AgentToolCall]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
