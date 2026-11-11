"""Preview structured SOC data or explicitly submit to the verified disposable QA API."""
import argparse
import json
import os
import re
from pathlib import Path
from soorin.e2e.local_validation import select_isolated_api, normalize_fixture, _load_fixture
from soorin.e2e.qa_target import verify_qa_target
from soorin.adapters.utopia.knowledge_client import KnowledgeClient
from soorin.contracts.native_profile import validate_native_event
from soorin.contracts.json_input import MAX_INPUT_BYTES
from soorin.ops.preview import preview


def submit(base, source, token, event):
    """Compatibility entry point; retries use the shared bounded native client."""
    return KnowledgeClient(base, source_token=token).ingest(source, event)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path, nargs='?')
    parser.add_argument('--raw', action='store_true', help='single structured SOC record, not scenario bundle')
    parser.add_argument('--tenant-id')
    parser.add_argument('--source-instance')
    parser.add_argument('--base-url', default='http://127.0.0.1:2526')
    parser.add_argument('--qa-project')
    parser.add_argument('--approved-port', type=int)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--receipts', metavar='KB_UUID', help='read admin receipt/job status; no submission')
    args = parser.parse_args(argv)
    try:
        if args.receipts:
            if args.execute or args.fixture:
                raise ValueError('receipts_cannot_be_combined_with_submission')
            client = KnowledgeClient(args.base_url, session_token=os.environ.get('UTOPIA_SESSION_TOKEN', ''))
            print(json.dumps(client.receipts(args.receipts), sort_keys=True))
            return 0
        if args.fixture is None:
            raise ValueError('input_file_required')
        with args.fixture.open('rb') as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('input_too_large')
        if args.raw:
            if not args.tenant_id or not args.source_instance:
                raise ValueError('tenant_and_source_instance_required')
            event, result = preview(raw, tenant_id=args.tenant_id, source_instance=args.source_instance)
            events = [('manual', event, result)]
        else:
            events = [(name, event, {'canonical_event': event.to_dict(), 'submission_status': 'NOT RUN'})
                      for name, event in normalize_fixture(_load_fixture(args.fixture))]
        for _, event, _ in events:
            validate_native_event(event)
        client = None
        if args.execute:
            base = select_isolated_api(args.base_url, qa_project=args.qa_project, approved_port=args.approved_port)
            verify_qa_target(base, args.qa_project)
            client = KnowledgeClient(base, source_token=os.environ.get('UTOPIA_INGEST_TOKEN', ''))
        for name, event, result in events:
            if client:
                result = {'receipt': client.ingest(os.environ.get('UTOPIA_SOURCE_ID', ''), event)}
            print(json.dumps({'scenario': name, **result}, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Do not echo input, tokens, paths, or provider bodies on failure.
        code = getattr(exc, 'code', '') or (str(exc) if re.fullmatch(r'[a-z_]{1,80}', str(exc)) else type(exc).__name__)
        parser.exit(2, f'ingestion failed: {code}; check input, scope, credentials and QA ownership\n')


if __name__ == '__main__':
    raise SystemExit(main())
