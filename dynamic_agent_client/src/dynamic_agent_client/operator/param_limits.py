"""Script name: param_limits.py. Apply instance-local constraints to tool schemas."""

from copy import deepcopy
import math

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


_KEYWORDS = {
    'enum', 'const', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
    'multipleOf', 'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems',
    'uniqueItems', 'items', 'properties', 'anyOf', 'allOf',
}
_LOWER = {'minimum', 'exclusiveMinimum', 'minLength', 'minItems'}
_UPPER = {'maximum', 'exclusiveMaximum', 'maxLength', 'maxItems'}


def _expand(schema: dict, root: dict, seen: tuple = ()) -> dict:
    """Copy a schema and resolve local definitions without sharing mutable nodes."""
    result = deepcopy(schema)
    if '$ref' in result:
        reference = result.pop('$ref')
        if not reference.startswith('#/') or reference in seen:
            raise ValueError('Injected parameters require nonrecursive local references')
        target = root
        for segment in reference[2:].split('/'):
            target = target[segment.replace('~1', '/').replace('~0', '~')]
        expanded = _expand(target, root, (*seen, reference))
        expanded.update(result)
        result = expanded
    for key in ('items',):
        if isinstance(result.get(key), dict):
            result[key] = _expand(result[key], root, seen)
    if 'properties' in result:
        result['properties'] = {key: _expand(value, root, seen)
                                for key, value in result['properties'].items()}
    for key in ('anyOf', 'allOf', 'oneOf'):
        if key in result:
            result[key] = [_expand(value, root, seen) for value in result[key]]
    return result


def _types(schema: dict) -> set:
    """Read declared types including nullable union branches."""
    value = schema.get('type', [])
    found = {value} if isinstance(value, str) else set(value)
    for branch in schema.get('anyOf', []):
        found.update(_types(branch))
    return found


def _merge(base: dict, limits: dict) -> dict:
    """Merge supported constraints while retaining static restrictions."""
    if not isinstance(limits, dict) or not limits:
        raise ValueError('Parameter limits must be a nonempty dictionary')
    unknown = set(limits) - _KEYWORDS
    if unknown:
        raise ValueError(f'Unsupported parameter limits: {sorted(unknown)}')
    result = deepcopy(base)
    types = _types(base)
    for key, value in limits.items():
        allowed = ({'array'} if key in {'items', 'minItems', 'maxItems', 'uniqueItems'} else
                   {'object'} if key == 'properties' else
                   {'string'} if key in {'minLength', 'maxLength', 'pattern'} else
                   {'number', 'integer'} if key in {
                       'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'
                   } else None)
        if allowed is not None and not types.intersection(allowed):
            raise ValueError(f'{key} is incompatible with declared parameter type')
        if key == 'items':
            if not isinstance(base.get('items'), dict):
                raise ValueError('Array items must have a declared schema')
            result[key] = _merge(base[key], value)
        elif key == 'properties':
            if not isinstance(value, dict) or set(value) - set(base.get('properties', {})):
                raise ValueError('Nested constraints must target declared properties')
            for name, constraints in value.items():
                result['properties'][name] = _merge(base['properties'][name], constraints)
        elif key in {'anyOf', 'allOf'}:
            if not isinstance(value, list) or not value:
                raise ValueError(f'{key} requires a nonempty list of constraints')
            # Keep static composition; dynamic branches can only narrow its choices.
            branches = [_merge(base, branch) for branch in value]
            result.setdefault('allOf', []).append({key: branches})
        else:
            if key in _LOWER and key in base and value < base[key]:
                raise ValueError(f'{key} cannot weaken a static limit')
            if key in _UPPER and key in base and value > base[key]:
                raise ValueError(f'{key} cannot weaken a static limit')
            if key == 'uniqueItems' and base.get(key) is True and value is not True:
                raise ValueError('uniqueItems cannot weaken a static limit')
            if key in {'enum', 'const'}:
                choices = value if key == 'enum' else [value]
                if not isinstance(choices, list) or not choices:
                    raise ValueError('enum requires a nonempty list')
                validator = Draft202012Validator(base)
                if any(not validator.is_valid(choice) for choice in choices):
                    raise ValueError('Choice violates the declared type or static constraints')
            # Different patterns/multiples must both hold rather than replace static rules.
            if key in {'pattern', 'multipleOf'} and key in base and value != base[key]:
                result.setdefault('allOf', []).append({key: deepcopy(base[key])})
            result[key] = deepcopy(value)
    if 'const' in result and 'enum' in result:
        constant = Draft202012Validator({'const': result['const']})
        result['enum'] = [choice for choice in result['enum'] if constant.is_valid(choice)]
    return result


def _check(schema: dict) -> None:
    """Reject invalid schemas and contradictory scalar or length bounds."""
    Draft202012Validator.check_schema(schema)
    for lower, upper in [('minLength', 'maxLength'), ('minItems', 'maxItems')]:
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise ValueError(f'{lower} exceeds {upper}')
    lows = [(schema[key], key == 'exclusiveMinimum') for key in ('minimum', 'exclusiveMinimum') if key in schema]
    highs = [(schema[key], key == 'exclusiveMaximum') for key in ('maximum', 'exclusiveMaximum') if key in schema]
    for low, low_exclusive in lows:
        for high, high_exclusive in highs:
            if low > high or (low == high and (low_exclusive or high_exclusive)):
                raise ValueError('Inconsistent numeric bounds')
    for key in ('enum', 'const'):
        if key in schema:
            validator = Draft202012Validator(schema)
            choices = schema[key] if key == 'enum' else [schema[key]]
            if any(not validator.is_valid(choice) for choice in choices):
                raise ValueError('Choice violates the effective constraints')
    for key, value in schema.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
            raise ValueError('Constraints must contain finite numbers')
        if key == 'properties':
            for child in value.values():
                _check(child)
        elif key == 'items' and isinstance(value, dict):
            _check(value)
        elif key in {'anyOf', 'allOf', 'oneOf'}:
            for child in value:
                _check(child)


def constrained_parameter(base: dict, limits: dict, root: dict) -> dict:
    """Build a validated constrained parameter without mutating its inputs."""
    try:
        Draft202012Validator.check_schema(limits)
        result = _merge(_expand(base, root), limits)
        _check(result)
        return result
    except (SchemaError, TypeError, KeyError, RecursionError) as error:
        raise ValueError(f'Invalid parameter limits: {error}') from error
