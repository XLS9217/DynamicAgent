class AgentResponseMessage(BaseMessage):
    type: Literal["agent_message"]
    text: str

class AgentResponseChunk(BaseMessage):
    type: Literal["agent_chunk"]
    text: str
    finished: bool = False # when false keep recv, else finish