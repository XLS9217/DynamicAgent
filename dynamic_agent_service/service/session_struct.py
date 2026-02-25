class AgentResponseMessage(BaseMessage):
    type: Literal["agent_message"]
    text: str = Field(..., min_length=1)
    tool_use: str = ""

class AgentResponseChunk(BaseMessage):
    type: Literal["agent_chunk"]
    text: str = Field(..., min_length=1)
    tool_use: str = ""
    finished: bool = False