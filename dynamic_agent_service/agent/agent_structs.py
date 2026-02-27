from pydantic import BaseModel


class AgentToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # this must be json string
    operator_name: str | None = None  # parsed from name prefix

class AgentInvokeResult(BaseModel):
    full_text: str
    tool_calls: list[AgentToolCall]