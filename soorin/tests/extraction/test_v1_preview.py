import json
import unittest
from unittest.mock import patch
from soorin.ops.preview import preview
from soorin.extraction import enrich_entities, NerProposal, extract_entities
from soorin.contracts.json_input import load_object

RECORD = {'alert_row_id': 'synthetic-alert', 'event_time': '2026-11-01T10:00:00Z',
          'host': 'host.example', 'src_ip': '10.0.0.1', 'network_scope': 'qa-a',
          'message': 'Synthetic example only'}


class PreviewTests(unittest.TestCase):
    def preview(self, record=RECORD, **kw):
        return preview(json.dumps(record), tenant_id='blue', source_instance='qa', **kw)

    def test_disabled_preview_is_offline_and_checksum_stable(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
            a, result = self.preview()
            b, _ = self.preview()
        self.assertEqual(a.content_checksum, b.content_checksum)
        self.assertFalse(result['persistent_writes'])
        self.assertEqual(result['ner_status'], 'disabled')
        self.assertTrue(a.entities)

    def test_invalid_or_ambiguous_input_is_rejected(self):
        for raw in ['{"alert_row_id":"a","alert_row_id":"b"}', '{"x":NaN}', '{"x":1e999}', '[]', '{',
                    '{"x":' * 34 + '{}' + '}' * 34, '{"x":"' + 'x' * 1048576 + '"}']:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                load_object(raw)
        for record in [{}, {**RECORD, 'alert_row_id':True}, {**RECORD, 'tenant_id': 'red'}, {**RECORD, 'llm_payload':'{"a":1,"a":2}'}]:
            with self.assertRaises(ValueError):
                self.preview(record)

    def test_mock_proposals_do_not_change_event_or_authority(self):
        class Provider:
            def extract(self, text):
                return [NerProposal('Host', 'host.example', .99, 'fake@1'),
                        NerProposal('Indicator', 'example-threat', .9, 'fake@1', 'MALWARE')]
        base, _ = self.preview()
        enriched, report = self.preview(ner=Provider())
        self.assertEqual(base.content_checksum, enriched.content_checksum)
        self.assertEqual(len(report['ner_proposals']), 1)
        self.assertTrue(report['ner_proposals'][0]['review_required'])
        self.assertNotIn('example-threat', [e.normalized_value for e in enriched.entities])

    def test_timeout_invalid_collection_and_unsupported_script_preserve_deterministic(self):
        class Provider:
            def extract(self, text):
                raise TimeoutError('private payload')
        batch = enrich_entities(RECORD, source_record_reference='a', ner=Provider())
        self.assertTrue(batch.deterministic.entities)
        self.assertEqual(batch.errors, ('ner_provider_error:TimeoutError',))
        class Invalid:
            def extract(self, text): return None
        self.assertIn('ner_provider_error:ValueError', enrich_entities(RECORD, source_record_reference='a', ner=Invalid()).errors)
        record = {**RECORD, 'message': 'گزارش آزمایشی'}
        _, result = self.preview(record, ner=Provider())
        self.assertIn('ner_unsupported_script', result['warnings'])

    def test_nested_hints_and_hash_algorithm_are_respected(self):
        batch = extract_entities({'nested': {'entity':'alice', 'entity_type':'user'}, 'sha256':'a'*32}, source_record_reference='a')
        self.assertEqual([(e.entity_type,e.normalized_value) for e in batch.entities], [('UserAccount','alice')])
        self.assertTrue(batch.errors)


class CurrentAgenticContractTests(unittest.TestCase):
    def test_api_enriched_alert_id_is_not_a_splunk_notable(self):
        from soorin.adapters.splunk import normalize_llm_payload
        payload = {'alert_id':'soc-row-1', 'event_time':'2026-11-01T10:00:00Z',
                   '_meta':{'provider':'splunk','mode':'enriched_from_api'}}
        event = normalize_llm_payload(payload, tenant_id='blue', source_instance='qa').event
        self.assertEqual(event.event_type, 'security_alert')
        self.assertFalse(any(e.entity_type == 'SplunkNotable' for e in event.entities))
        self.assertEqual(next(e for e in event.entities if e.entity_type == 'SecurityAlert').source_identifiers,
                         {'soc_alert_row_id':'soc-row-1'})
        with self.assertRaisesRegex(ValueError, 'conflicting_soc_alert_identity'):
            normalize_llm_payload(payload, tenant_id='blue', source_instance='qa', raw_record={'alert_row_id':'different'})
        legacy = {**payload, '_meta':{}}
        event = normalize_llm_payload(legacy, tenant_id='blue', source_instance='qa').event
        self.assertEqual(event.event_type, 'splunk_notable')
