from pydantic import BaseModel


class BlueprintAttributeSchema(BaseModel):
    description: str
    is_identifier: bool = False


class Blueprint(BaseModel):
    name: str
    description: str
    attributes: dict[str, BlueprintAttributeSchema]


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