from typing import Literal
from pydantic import BaseModel

class AgentResponseMessage(BaseModel):
    type: Literal["agent_message"]
    text: str


class AgentResponseChunk(BaseModel):
    type: Literal["agent_chunk"]
    text: str
    finished: bool = False