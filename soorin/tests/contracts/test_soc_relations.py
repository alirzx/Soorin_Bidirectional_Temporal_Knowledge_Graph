from dataclasses import replace
import json
from pathlib import Path
import unittest
from soorin.adapters.splunk import normalize_llm_payload
from soorin.contracts import SecurityKnowledgeEvent, CanonicalEntity, KnowledgeRelation, EvidenceReference
from soorin.contracts.native_profile import validate_native_event

TIME = '2026-11-05T10:00:00Z'

class SocRelationTests(unittest.TestCase):
    def event(self, subject='SecurityAlert', obj='Host', relation='observed_on', evidence=('e',)):
        return SecurityKnowledgeEvent('t','splunk','s','A','event','alert',TIME,TIME,TIME,
            entities=(CanonicalEntity('soorin:a',subject,'A'),CanonicalEntity('soorin:b',obj,'B')),
            evidence=(EvidenceReference('e','A'),),
            relations=(KnowledgeRelation('r',relation,'soorin:a','soorin:b',evidence_ids=evidence),))

    def test_reviewed_spelling_and_valid_signatures(self):
        for spelling in ['observed_on','OBSERVED_ON','observed on','observedOn']:
            validate_native_event(self.event(relation=spelling))

    def test_unknown_relation_invalid_domain_range_and_evidence(self):
        for event, code in [(self.event(relation='unreviewed relation'),'soc_relation_type_unknown'),
                            (self.event(subject='Ticket'),'soc_relation_domain_invalid'),
                            (self.event(obj='UserAccount'),'soc_relation_range_invalid'),
                            (self.event(evidence=()),'soc_relation_evidence_required')]:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError,code):
                validate_native_event(event)
        with self.assertRaisesRegex(ValueError,'invalid_entity_reference'):
            replace(self.event(), entities=self.event().entities[:1], content_checksum=None)
        with self.assertRaisesRegex(ValueError,'invalid_evidence_reference'):
            replace(self.event(), evidence=(), content_checksum=None)

    def test_all_existing_normalized_scenarios_meet_native_signature_policy(self):
        fixtures = Path(__file__).parents[1] / 'fixtures'
        for name in ['soc_llm_payload_scenarios_v1.json', 'soc_e2e_scenarios_v1.json']:
            for row in json.loads((fixtures / name).read_text())['records']:
                with self.subTest(fixture=name,scenario=row['scenario']):
                    event = normalize_llm_payload(row.get('llm_payload'), tenant_id=row['tenant_id'],
                        source_instance=row['source_instance'],raw_record=row['raw_record']).event
                    validate_native_event(event)

    def test_notable_ticket_uses_explicit_case_and_never_invents_alert(self):
        for has_case in [False,True]:
            raw={'notable_id':'N','ticket_id':'T','_time':TIME}
            if has_case:raw['case_id']='C'
            normalized=normalize_llm_payload(None,tenant_id='t',source_instance='s',raw_record=raw)
            kinds={e.entity_id:e.entity_type for e in normalized.event.entities}
            links=[r for r in normalized.event.relations if r.relation_type=='TRACKED_BY_TICKET']
            self.assertNotIn('SecurityAlert',kinds.values())
            self.assertEqual(len(links),int(has_case))
            if links:self.assertEqual(kinds[links[0].subject_entity_id],'SOCCase')
            else:self.assertIn('ticket_link_requires_alert_or_case',normalized.warnings)
            validate_native_event(normalized.event)

    def test_source_mapping_and_correlation_are_assertions(self):
        normalized=normalize_llm_payload({'alert_id':'N','event_time':TIME,'mitre_technique_id':'T1059'},
            tenant_id='t',source_instance='s',raw_record={'alert_row_id':'A','notable_id':'N','_time':TIME})
        for relation in normalized.event.relations:
            if relation.relation_type in {'CORRELATED_WITH','MAPPED_TO_TECHNIQUE'}:
                self.assertEqual(relation.confidence_category,'asserted')
