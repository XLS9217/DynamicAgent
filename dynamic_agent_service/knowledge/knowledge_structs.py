from pydantic import BaseModel


class Blueprint(BaseModel):
    name:str
    description: str
    attributes: dict[str, str]  # attribute_name -> attribute_description