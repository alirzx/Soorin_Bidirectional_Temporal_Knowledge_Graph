"""Source-side minimization before checksum creation; not a DLP classifier."""
from __future__ import annotations
from collections.abc import Mapping

SENSITIVE_KEYS = frozenset({'_raw', 'raw', 'raw_record', 'raw_payload', 'message', 'log', 'logs',
                           'password', 'passwd', 'secret', 'token', 'access_token', 'api_key',
                           'authorization', 'cookie', 'credentials', 'prompt', 'response'})


def minimize(value):
    if isinstance(value, Mapping):
        return {key: minimize(item) for key, item in value.items()
                if str(key).lower() not in SENSITIVE_KEYS}
    if isinstance(value, (list, tuple)):
        return [minimize(item) for item in value]
    return value
