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
            return subprocess.run([sys.executable, '-S', '-m', 'soorin.ops.http_adapter'],
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

    def test_adapter_imports_from_explicit_root_without_site_packages(self):
        import os
        import tempfile
        root = Path(__file__).parents[3]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-S', '-m', 'soorin.ops.http_adapter'],
                input=json.dumps({'scope':SCOPE,'http_body':json.dumps({'profile':PROFILE,'record':RECORD})}).encode(),
                cwd=directory, env={**os.environ,'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1'},
                capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('canonical_event',json.loads(result.stdout))

    def test_nested_scope_and_duplicate_keys_fail_closed(self):
        for wrapper in ['raw_event','raw_data','alert']:
            nested = {**RECORD,'tenant_id':'another-tenant'}
            with self.subTest(wrapper=wrapper), self.assertRaises(ValueError):
                normalize(self.request(record={**RECORD,wrapper:json.dumps(nested) if wrapper=='raw_data' else nested}))
        with self.assertRaises(ValueError):
            normalize(self.request(record={**RECORD,'source_system':'edr'}))

    def test_nested_curated_payload_preserves_producer_identity_marker(self):
        record = {**RECORD,'raw_data':json.dumps({'llm_payload':{
            'alert_id':'synthetic-alert','_meta':{'mode':'enriched_from_api'},
            'event_time':RECORD['event_time']}})}
        result = normalize(self.request(record=record))
        entities = result['canonical_event']['entities']
        self.assertEqual(len([e for e in entities if e['entity_type']=='SecurityAlert']),1)
        self.assertFalse(any(e['entity_type']=='SplunkNotable' for e in entities))

    def test_malformed_transport_never_emits_source_or_traceback(self):
        for wire in [b'[]', b'{', b'{"scope":1}',
                     b'{"http_body":"private","http_body":"other","scope":{}}']:
            result = subprocess.run([sys.executable,'-S','-m','soorin.ops.http_adapter'],input=wire,
                capture_output=True,timeout=5,cwd=Path(__file__).parents[3])
            self.assertEqual(result.returncode,2)
            self.assertEqual(result.stdout+result.stderr,b'')

    def test_nested_payload_strings_preserve_duplicate_key_rejection(self):
        for payload in ['{', '{"alert_id":"a","alert_id":"b"}', '{"score":NaN}']:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                normalize(self.request(record={**RECORD,'raw_event':{'llm_payload':payload}}))
