"""Bounded JSON ingress; duplicate keys and non-finite numbers are ambiguous."""
import json
import math

MAX_INPUT_BYTES = 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('non_finite_json_number')


def load_object(raw: str | bytes):
    if len(raw.encode('utf-8') if isinstance(raw, str) else raw) > MAX_INPUT_BYTES:
        raise ValueError('input_too_large')
    try:
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except (RecursionError, UnicodeError, json.JSONDecodeError):
        raise ValueError('invalid_json_object') from None
    if not isinstance(value, dict):
        raise ValueError('expected_json_object')
    # Also bound nesting before downstream recursive minimization/extraction.
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 32:
            raise ValueError('json_nesting_limit')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non_finite_json_number")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return value
