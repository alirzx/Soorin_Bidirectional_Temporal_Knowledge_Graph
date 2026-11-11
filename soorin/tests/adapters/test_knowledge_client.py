import json
from pathlib import Path
import unittest
from soorin.contracts import SecurityKnowledgeEvent
from soorin.adapters.utopia.knowledge_client import KnowledgeClient, KnowledgeClientError

ID = '00000000-0000-0000-0000-000000000001'

class KnowledgeClientTests(unittest.TestCase):
    def event(self):
        data = json.loads((Path(__file__).parents[1] / 'fixtures/soc_canonical_minimal_v1.json').read_text())
        return SecurityKnowledgeEvent.from_dict(data['event'])

    def test_retries_exact_event_bytes_and_does_not_log_error_body(self):
        calls = []
        def transport(method, url, headers, body):
            calls.append(body)
            return (503, {'private': 'secret'}) if len(calls) == 1 else (200, {'schema_version': 'soorin.ingestion-receipt.v1'})
        client = KnowledgeClient('http://127.0.0.1:2516', source_token='synthetic', transport=transport, sleep=lambda _: None)
        client.ingest(ID, self.event())
        self.assertEqual(calls[0], calls[1])

    def test_unauthorized_redirect_and_schema_fail_without_retry(self):
        for status in [401, 403, 404, 302, 422, 200]:
            calls = []
            def transport(*args):
                calls.append(1)
                return status, {'private': 'secret'}
            client = KnowledgeClient('https://soorin.example.invalid', session_token='synthetic', transport=transport)
            with self.assertRaises(KnowledgeClientError) as error:
                client.context(ID, tenant_id='blue', entity='host')
            self.assertEqual(len(calls), 1)
            self.assertNotIn('secret', str(error.exception))

    def test_endpoint_and_history_guards(self):
        for url in ['http://outside.invalid', 'https://u:p@outside.invalid', 'https://outside.invalid?key=x']:
            with self.assertRaises(ValueError):
                KnowledgeClient(url)
        with self.assertRaises(ValueError):
            KnowledgeClient('https://outside.invalid').context(ID, tenant_id='blue', entity='current alias', as_of='2026-01-01T00:00:00Z')


    def test_receipt_diagnostics_and_resolution_use_separate_reader_credential(self):
        calls = []
        def transport(method, url, headers, body):
            calls.append((method, url, headers, body))
            schema = 'soorin.ingestion-status.v1' if method == 'GET' else 'soorin.identity-resolution.v1'
            return 200, {'schema_version':schema}
        client = KnowledgeClient('http://127.0.0.1:2526', source_token='source-only', session_token='reader-only', transport=transport)
        client.receipts(ID)
        client.resolve(ID, tenant_id='blue', source_system='splunk', source_instance='one',
                       entity_type='Host', authority_name='host_id', source_identifier='one')
        self.assertEqual(calls[0][0], 'GET')
        self.assertIsNone(calls[0][3])
        self.assertTrue(all(c[2]['Authorization'] == 'Bearer reader-only' for c in calls))
