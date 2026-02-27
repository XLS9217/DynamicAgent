from pydantic import BaseModel


class AgentToolCall(BaseModel):
    id: str
    name: str
    arguments: str #this must be json string

class AgentInvokeResult(BaseModel):
    full_text: str
    tool_calls: list[AgentToolCall]