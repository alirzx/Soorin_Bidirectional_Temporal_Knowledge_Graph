import json
from pathlib import Path
import subprocess
import sys
import unittest
from soorin.ops.http_adapter import PROFILE, normalize
from soorin.ops.preview import preview

RECORD = {'alert_row_id': 'synthetic-alert', 'event_time': '2026-11-01T10:00:00Z',
          'host': 'host.example'}
SCOPE = {'tenant_id': 'blue', 'source_system': 'splunk', 'source_instance': 'qa'}


class HttpAdapterTests(unittest.TestCase):
    def request(self, **changes):
        return {**SCOPE, 'profile': PROFILE, 'record': RECORD, **changes}

    def test_same_contract_and_checksum_as_existing_cli(self):
        result = normalize(self.request())
        event, _ = preview(json.dumps(RECORD), tenant_id='blue', source_instance='qa')
        self.assertEqual(result['canonical_event']['content_checksum'], event.content_checksum)
        self.assertFalse(result['persistent_writes'])
        self.assertEqual(result['ner_status'], 'disabled')

    def test_unknown_profile_batch_and_scope_override_rejected(self):
        for changes in [{'profile': 'unknown'}, {'record': [RECORD]},
                        {'source_system': 'agentic_soc'}, {'record': {**RECORD, 'tenant_id': 'red'}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize(self.request(**changes))

    def test_one_shot_protocol_and_duplicate_keys(self):
        def run(public):
            return subprocess.run([sys.executable, '-m', 'soorin.ops.http_adapter'],
                input=json.dumps({'scope': SCOPE, 'http_body': public}).encode(),
                capture_output=True, timeout=5, cwd=Path(__file__).parents[3])
        good = run(json.dumps({'profile': PROFILE, 'record': RECORD}))
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn('canonical_event', json.loads(good.stdout))
        bad = run('{"profile":"private-one","profile":"private-two","record":{}}')
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout + bad.stderr, b'')

    def test_ocsf_raw_data_string_and_nested_assets(self):
        record = {**RECORD, 'finding': {'uid': 'finding-1'}, 'raw_data': json.dumps({
            'raw_event': {'notable_id': 'notable-1', 'assets': [
                {'hostname': 'one.example'}, {'hostname': 'two.example'}]}})}
        result = normalize(self.request(record=record))['canonical_event']
        entities = {(e['entity_type'], e['normalized_value']) for e in result['entities']}
        self.assertIn(('SplunkNotable', 'notable-1'), entities)
        self.assertIn(('SecurityEvent', 'finding-1'), entities)
        self.assertIn(('Host', 'two.example'), entities)
        for value in ['{', '[]', '{"host":"a","host":"b"}']:
            with self.assertRaises(ValueError):
                normalize(self.request(record={**RECORD, 'raw_data': value}))
