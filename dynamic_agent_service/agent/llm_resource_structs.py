from pydantic import BaseModel, Field


class LLMResourceCreate(BaseModel):
    model: str
    api_key: str = Field(repr=False)
    base_url: str
    enabled: bool = True
    priority: int = 0


class LLMResource(LLMResourceCreate):
    resource_id: str


class LLMResourceUpdate(BaseModel):
    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    base_url: str | None = None
    enabled: bool | None = None
    priority: int | None = None
