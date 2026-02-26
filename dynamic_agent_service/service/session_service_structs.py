from typing import Literal
from pydantic import BaseModel


class AgentResponseChunk(BaseModel):
    """
    text stream response
    """
    type: Literal["agent_chunk"]
    text: str
    finished: bool = False