"""Models for persisted OpenAI-compatible API resources."""

from datetime import datetime

from pydantic import BaseModel, Field


class OpenAIResourceCreate(BaseModel):
    model: str
    api_key: str = Field(repr=False)
    base_url: str
    enabled: bool = True
    priority: int = 0


class OpenAIResource(OpenAIResourceCreate):
    resource_id: str
    deleted_at: datetime | None = None


class OpenAIResourceUpdate(BaseModel):
    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    base_url: str | None = None
    enabled: bool | None = None
    priority: int | None = None
