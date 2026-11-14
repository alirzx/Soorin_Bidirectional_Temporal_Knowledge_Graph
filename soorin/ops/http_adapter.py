"""Bounded one-shot normalization worker for authenticated native HTTP routes.

No database, network, model or durable queue. Source scope comes from the Rust
server, never from the submitted record. Protocol is one JSON object on stdin.
"""
import json
import sys
from soorin.contracts.json_input import load_object, MAX_INPUT_BYTES
from soorin.ops.preview import preview

PROFILE = 'agentic-soc.splunk-curated.v1'


def normalize(request):
    if set(request) != {'profile', 'record', 'tenant_id', 'source_system', 'source_instance'}:
        raise ValueError('invalid_adapter_envelope')
    if request['profile'] != PROFILE or request['source_system'] != 'splunk':
        raise ValueError('unsupported_source_profile')
    if not isinstance(request['record'], dict):
        raise ValueError('record_must_be_object')
    event, result = preview(json.dumps(request['record']), tenant_id=request['tenant_id'],
                            source_instance=request['source_instance'])
    # Extraction warnings can contain invalid source values. HTTP diagnostics
    # expose warning categories only; local CLI preview keeps its own detail.
    result['warnings'] = sorted({w.split(':', 1)[0] for w in result['warnings']})
    return result


def main():
    try:
        wire = sys.stdin.buffer.read(2 * MAX_INPUT_BYTES + 1)
        if len(wire) > 2 * MAX_INPUT_BYTES:
            raise ValueError('adapter_transport_too_large')
        transport = json.loads(wire)
        public = load_object(transport['http_body'])
        if set(public) != {'profile', 'record'}:
            raise ValueError('invalid_public_envelope')
        result = normalize({**public, **transport['scope']})
        encoded = json.dumps(result, ensure_ascii=False).encode()
        if len(encoded) > MAX_INPUT_BYTES:
            raise ValueError('normalized_output_too_large')
        sys.stdout.buffer.write(encoded)
    except (ValueError, TypeError, KeyError):
        # Never print exceptions or source values to the app's logs.
        sys.exit(2)


if __name__ == '__main__':
    main()
