from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class AgentResponseChunk(BaseModel):
    """Agent lifecycle or text event sent by the service."""

    type: Literal["agent_chunk"]
    text: str
    finished: bool = False
    invoked: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    runner_id: str | None = None
    runner_name: str | None = None
    parent_runner_id: str | None = None
    parent_tool_call_id: str | None = None


class AgentToolCallMessage(BaseModel):
    """Operator tool call sent by the service for local execution."""

    type: Literal["tool_call"]
    session_id: str
    runner_id: str
    tool_call_id: str
    name: str
    arguments: dict = Field(default_factory=dict)


ServiceToClientMessage = Annotated[
    AgentResponseChunk | AgentToolCallMessage,
    Field(discriminator="type"),
]

service_to_client_message_adapter = TypeAdapter(ServiceToClientMessage)
