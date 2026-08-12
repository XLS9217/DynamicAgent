"""Canonical structure for one flat file-based invocation log record."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class InvokeLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoke_id: str
    trigger_id: str | None = None
    runner_id: str
    parent_runner_id: str | None = None
    text: str | None = None
    tool_id: str | None = None
    tool_use: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    resource_id: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    usage_detail: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
