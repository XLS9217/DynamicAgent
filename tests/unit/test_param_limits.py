"""Script name: test_param_limits.py. Verify dynamic schemas without services."""

from typing import Annotated, Literal
import unittest

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from dynamic_agent_client import AgentOperator, agent_tool


class Row(BaseModel):
    """Declare the fields that nested constraints can target."""

    model_config = ConfigDict(extra='forbid')
    category: str
    label: str | None


class Example(AgentOperator):
    """Expose static and nested argument types for isolation checks."""

    @agent_tool(description='Submit choices')
    async def submit(self, labels: list[str], rows: list[Row], other: list[Row],
                     count: Annotated[int, Field(ge=1, le=20)] = 5,
                     status: Literal['ok', 'deferred'] = 'ok'):
        """Return ordinary dictionaries without runtime conversion."""
        return rows


def parameters(operator):
    """Return one fresh serialized argument schema."""
    return operator.get_serialized_operator().tools[0]['function']['parameters']


class ParamLimitTests(unittest.IsolatedAsyncioTestCase):
    """Verify narrowing, serializations, rejected injections, and compatibility."""

    def test_enum_isolation_repeated_injection_and_snapshot(self):
        """Keep caller dictionaries, other instances, and prior snapshots isolated."""
        first, second = Example(), Example()
        before = parameters(first)
        limits = {'items': {'enum': ['A', 'B']}, 'maxItems': 2}
        first.inject_param_limit('submit', 'labels', limits)
        limits['items']['enum'].append('C')
        first.inject_param_limit('submit', 'labels', {'minItems': 1})
        schema = parameters(first)
        self.assertEqual(schema['properties']['labels']['items'],
                         {'type': 'string', 'enum': ['A', 'B']})
        self.assertEqual(schema['properties']['labels']['minItems'], 1)
        self.assertEqual(parameters(second), before)
        schema['properties']['labels']['items']['enum'].append('tamper')
        self.assertNotIn('tamper', str(parameters(first)))
        first.inject_param_limit('submit', 'labels', {'items': {'enum': ['D']}})
        self.assertEqual(parameters(first)['properties']['labels']['items']['enum'], ['D'])
        self.assertEqual(parameters(Example()), before)

    def test_private_references_and_category_specific_branches(self):
        """Constrain one referenced row without changing another argument."""
        operator = Example()
        before = parameters(operator)
        operator.inject_param_limit('submit', 'rows', {'items': {'anyOf': [
            {'properties': {'category': {'enum': ['A']}, 'label': {'enum': ['X', None]}}},
            {'properties': {'category': {'enum': ['B']}, 'label': {'enum': ['Y', None]}}},
        ]}})
        schema = parameters(operator)
        self.assertEqual(schema['properties']['other'], before['properties']['other'])
        self.assertEqual(schema['$defs'], before['$defs'])
        validate = Draft202012Validator(schema).is_valid
        common = {'labels': [], 'other': []}
        self.assertTrue(validate({**common, 'rows': [{'category': 'A', 'label': 'X'}]}))
        self.assertTrue(validate({**common, 'rows': [{'category': 'B', 'label': None}]}))
        self.assertFalse(validate({**common, 'rows': [{'category': 'A', 'label': 'Y'}]}))

    def test_invalid_limits_are_atomic(self):
        """Reject misspellings, structural changes, type errors, and contradictions."""
        operator = Example()
        before = parameters(operator)
        cases = [
            ('missing', 'labels', {'maxItems': 2}),
            ('submit', 'missing', {'enum': ['x']}),
            ('submit', 'labels', {'type': 'string'}),
            ('submit', 'labels', {'items': {'enum': []}}),
            ('submit', 'labels', {'items': {'enum': [1]}}),
            ('submit', 'labels', {'minItems': 3, 'maxItems': 2}),
            ('submit', 'labels', {'maxItems': '2'}),
            ('submit', 'count', {'minimum': 0}),
            ('submit', 'count', {'minimum': 5, 'exclusiveMaximum': 5}),
            ('submit', 'count', {'enum': [21]}),
            ('submit', 'count', {'minLength': 2}),
            ('submit', 'status', {'enum': ['unknown']}),
            ('submit', 'rows', {'items': {'properties': {'missing': {'enum': ['x']}}}}),
        ]
        for tool, parameter, limits in cases:
            with self.subTest(limits=limits, parameter=parameter):
                with self.assertRaises(ValueError):
                    operator.inject_param_limit(tool, parameter, limits)
                self.assertEqual(parameters(operator), before)

    def test_static_defaults_and_runtime_behavior_remain(self):
        """Schema injection leaves Python call semantics and defaults unchanged."""
        operator = Example()
        before = parameters(operator)
        operator.inject_param_limit('submit', 'count', {'minimum': 3, 'maximum': 10})
        schema = parameters(operator)
        self.assertEqual(schema['required'], before['required'])
        self.assertEqual(schema['properties']['count']['default'], 5)
        self.assertEqual(schema['properties']['count']['maximum'], 10)

    def test_const_can_narrow_a_static_enum(self):
        """Keep only the constant choice while preserving the annotated enum."""
        operator = Example()
        operator.inject_param_limit('submit', 'status', {'const': 'ok'})
        status = parameters(operator)['properties']['status']
        self.assertEqual(status['enum'], ['ok'])
        self.assertEqual(status['const'], 'ok')

    async def test_execution_does_not_coerce_or_validate(self):
        """Keep business validation under the tool implementation's control."""
        operator = Example()
        operator.inject_param_limit('submit', 'labels', {'items': {'enum': ['A']}})
        rows = [{'category': 'A', 'label': None}]
        self.assertIs(await operator.execute('submit', {'labels': ['other'],
                      'rows': rows, 'other': []}), rows)


if __name__ == '__main__':
    unittest.main()
