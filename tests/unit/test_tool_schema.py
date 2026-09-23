"""Script name: test_tool_schema.py. Specify the SDK tool schema contract without live services."""

import unittest
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dynamic_agent_client import AgentOperator, agent_tool


class SearchFilter(BaseModel):
    """Describe allowed search filters and their defaults."""

    model_config = ConfigDict(extra="forbid")

    # Required field with a constrained set of values.
    category: Literal["article", "video"]
    # Optional field with typed values inside an object.
    scores: dict[str, float] = Field(default_factory=dict)
    # Nullable does not imply optional: this field must still be supplied.
    owner: str | None
    # A default makes this field optional to supply.
    limit: int = Field(default=10, ge=1, description="Maximum results")


class FancySchemaOperator(AgentOperator):
    """Demonstrate the desired annotation-driven tool API."""

    @agent_tool(description="Inspect basic argument types")
    async def basic(self, metadata: dict, count: int, ratio: float, enabled: bool, label: str) -> dict:
        """Return basic values unchanged.

        :param metadata: Arbitrary metadata fields.
        :param count: Number of records.
        """
        return dict(metadata=metadata, count=count, ratio=ratio, enabled=enabled, label=label)

    @agent_tool(description="Describe a structured search")
    async def search(
        self,
        filters: SearchFilter,
        matrix: list[list[int]],
        groups: dict[str, list[float]],
        key: str | int,
        mode: Literal["fast", "thorough"] = "fast",
        note: str | None = None,
    ) -> str:
        """Accept nested annotations without a manually written JSON Schema.

        :param filters: Allowed search filters.
        :param matrix: Rows of integer values.
        """
        return "Search accepted"


def resolve(schema: dict, root: dict) -> dict:
    """Resolve local JSON Schema references while allowing inline schemas."""
    while "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/"):
            raise AssertionError(f"Expected a local reference, got {reference}")
        schema = root
        for part in reference[2:].split("/"):
            schema = schema[part.replace("~1", "/").replace("~0", "~")]
    return schema


class FancySchemaTest(unittest.TestCase):
    """Check public serialized tools rather than a specific schema implementation."""

    def setUp(self):
        """Build the same tool definitions that operator registration sends."""
        tools = FancySchemaOperator().get_serialized_operator().tools
        self.tools = {tool["function"]["name"]: tool for tool in tools}
        self.basic = self.tools["FancySchemaOperator_basic"]["function"]["parameters"]
        self.search = self.tools["FancySchemaOperator_search"]["function"]["parameters"]

    def test_tool_wrapper_and_parameter_descriptions(self):
        """Preserve the function wrapper, tool names, and docstring descriptions."""
        tool = self.tools["FancySchemaOperator_basic"]
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["function"]["description"], "Inspect basic argument types")
        self.assertEqual(self.basic["type"], "object")
        self.assertNotIn("self", self.basic["properties"])
        self.assertEqual(self.basic["properties"]["count"]["description"], "Number of records.")

    def test_basic_types(self):
        """Map Python primitives to their correct JSON Schema types."""
        expected = dict(metadata="object", count="integer", ratio="number", enabled="boolean", label="string")
        for name, kind in expected.items():
            with self.subTest(argument=name):
                self.assertEqual(self.basic["properties"][name]["type"], kind)
        self.assertEqual(set(self.basic["required"]), set(expected))

    def test_recursive_containers(self):
        """Describe nested lists and dictionaries recursively."""
        matrix = self.search["properties"]["matrix"]
        self.assertEqual(matrix["type"], "array")
        self.assertEqual(matrix["items"]["type"], "array")
        self.assertEqual(matrix["items"]["items"]["type"], "integer")
        groups = self.search["properties"]["groups"]
        self.assertEqual(groups["type"], "object")
        self.assertEqual(groups["additionalProperties"]["type"], "array")
        self.assertEqual(groups["additionalProperties"]["items"]["type"], "number")

    def test_unions_literals_and_defaults(self):
        """Distinguish allowed values, nullable types, and optional arguments."""
        properties = self.search["properties"]
        self.assertEqual({item["type"] for item in properties["key"]["anyOf"]}, {"string", "integer"})
        self.assertEqual({item["type"] for item in properties["note"]["anyOf"]}, {"string", "null"})
        self.assertEqual(set(properties["mode"]["enum"]), {"fast", "thorough"})
        self.assertEqual(properties["mode"]["default"], "fast")
        self.assertIn("default", properties["note"])
        self.assertIsNone(properties["note"]["default"])
        self.assertEqual(set(self.search["required"]), {"filters", "matrix", "groups", "key"})

    def test_structured_model_fields(self):
        """Expose model fields, requiredness, constraints, and extra-field policy."""
        filters = resolve(self.search["properties"]["filters"], self.search)
        self.assertEqual(filters["type"], "object")
        self.assertEqual(set(filters["properties"]), {"category", "scores", "owner", "limit"})
        self.assertEqual(set(filters["required"]), {"category", "owner"})
        self.assertIs(filters["additionalProperties"], False)
        fields = filters["properties"]
        self.assertEqual(set(fields["category"]["enum"]), {"article", "video"})
        self.assertEqual(fields["scores"]["additionalProperties"]["type"], "number")
        self.assertEqual({item["type"] for item in fields["owner"]["anyOf"]}, {"string", "null"})
        self.assertEqual(fields["limit"]["type"], "integer")
        self.assertEqual(fields["limit"]["minimum"], 1)
        self.assertEqual(fields["limit"]["default"], 10)
        self.assertEqual(fields["limit"]["description"], "Maximum results")


if __name__ == "__main__":
    unittest.main(verbosity=2)
