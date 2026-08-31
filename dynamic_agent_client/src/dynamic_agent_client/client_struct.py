from typing import Annotated, Any, Literal

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


class AgentInvocationEvent(BaseModel):
    """One completed provider-model invocation assembled from agent chunks.

    ``text`` contains the assistant text accumulated since the runner's previous
    invocation. It may be empty when the model responds only with tool calls.
    Token fields are ``None`` when the provider did not report usage; a reported
    zero remains distinct from unavailable usage.
    """

    type: Literal["agent_invocation"] = "agent_invocation"
    session_id: str
    invocation_id: str
    runner_id: str
    runner_name: str | None = None
    parent_runner_id: str | None = None
    parent_tool_call_id: str | None = None
    finished: bool = False
    text: str = ""
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ToolExecutionEvent(BaseModel):
    """One lifecycle update for a client-executed operator tool."""

    type: Literal["tool_execution"] = "tool_execution"
    session_id: str
    runner_id: str
    tool_call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["started", "succeeded", "failed"]
    result: Any | None = None
    error: str | None = None


AgentEvent = Annotated[
    AgentInvocationEvent | ToolExecutionEvent,
    Field(discriminator="type"),
]


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
