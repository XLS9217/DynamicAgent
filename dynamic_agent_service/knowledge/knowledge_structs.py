from pydantic import BaseModel, model_validator


class BlueprintAttributeSchema(BaseModel):
    description: str
    is_identifier: bool = False


class Blueprint(BaseModel):
    id: str | None = None
    name: str
    description: str
    attributes: dict[str, BlueprintAttributeSchema]

    @model_validator(mode="after")
    def exactly_one_identifier(self):
        count = sum(1 for a in self.attributes.values() if a.is_identifier)
        if count != 1:
            raise ValueError(f"Blueprint must have exactly 1 identifier attribute, got {count}")
        return self


class BlueprintAttribute(BaseModel):
    id: str
    blueprint_id: str
    name: str
    description: str
    is_identifier: bool = False


class BlueprintInstance(BaseModel):
    id: str
    instance_id: str
    attribute_id: str