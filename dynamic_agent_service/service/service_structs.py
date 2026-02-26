from typing import Literal, Optional
from pydantic import BaseModel

from dynamic_agent_service.agent.agent_structs import AgentToolCall


class AgentResponseChunk(BaseModel):
    """
    text stream response
    """
    type: Literal["agent_chunk"]
    text: str
    tool_call: Optional[AgentToolCall] = None
    finished: bool = False
