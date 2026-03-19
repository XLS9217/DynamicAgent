from pydantic import BaseModel


class Blueprint(BaseModel):
    name: str
    description: str
    attributes: dict[str, str]  # attribute_name -> attribute_description


class BlueprintAttribute(BaseModel):
    id: str
    blueprint_id: str
    name: str
    description: str


class BlueprintInstance(BaseModel):
    id: str
    instance_id: str
    attribute_id: str