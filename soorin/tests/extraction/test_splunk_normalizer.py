from __future__ import annotations

import json
from pathlib import Path
import unittest

from soorin.adapters.splunk.llm_payload_normalizer import NormalizationError, normalize_llm_payload

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "soc_llm_payload_scenarios_v1.json"


class SplunkNormalizerTests(unittest.TestCase):
    def test_same_address_in_distinct_fields_preserves_network_scope(self):
        event = normalize_llm_payload(None, tenant_id="t", source_instance="s", raw_record={
            "alert_row_id": "A1", "case_id": "C1", "_time": "2026-01-01T00:00:00Z",
            "src_ip": "10.0.0.1", "dest_ip": "10.0.0.1",
            "network_scopes": {"src_ip": "vpc-a", "dest_ip": "vpc-b"},
        }).event
        ips = [entity for entity in event.entities if entity.entity_type == "IPAddress"]
        self.assertEqual({entity.scope for entity in ips}, {"vpc-a", "vpc-b"})
        self.assertEqual(len({entity.entity_id for entity in ips}), 2)
        self.assertIn("PART_OF_CASE", {relation.relation_type for relation in event.relations})

    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_is_synthetic_and_all_scenarios_normalize(self):
        self.assertTrue(self.dataset["synthetic"])
        for row in self.dataset["records"]:
            normalized = normalize_llm_payload(
                row["llm_payload"], tenant_id=row["tenant_id"], source_instance=row["source_instance"],
                raw_record=row["raw_record"], observed_at="2026-10-31T00:00:00Z",
            )
            self.assertEqual(normalized.event.tenant_id, "tenant-blue", row["scenario"])
            self.assertTrue(normalized.event.entities, row["scenario"])

    def test_missing_payload_uses_documented_fallback(self):
        row = next(item for item in self.dataset["records"] if item["scenario"] == "missing_llm_payload")
        out = normalize_llm_payload(None, tenant_id=row["tenant_id"], source_instance=row["source_instance"], raw_record=row["raw_record"], observed_at="2026-10-31T00:00:00Z")
        self.assertIn("missing_llm_payload_compact_fallback", out.warnings)
        self.assertIsNone(out.event.curated_payload_version)

    def test_unknown_event_time_falls_back_to_alert_time(self):
        row = next(item for item in self.dataset["records"] if item["scenario"] == "unknown_event_time")
        out = normalize_llm_payload(row["llm_payload"], tenant_id=row["tenant_id"], source_instance=row["source_instance"], raw_record=row["raw_record"], observed_at="2026-10-31T00:00:00Z")
        self.assertIn("event_time_fell_back_to_alert_time", out.warnings)
        self.assertEqual(out.verified_source_metadata["event_time_source"], "alert_time_fallback")

    def test_risk_score_and_hints_are_not_conclusions(self):
        row = self.dataset["records"][0]
        out = normalize_llm_payload(row["llm_payload"], tenant_id=row["tenant_id"], source_instance=row["source_instance"], raw_record=row["raw_record"], observed_at="2026-10-31T00:00:00Z")
        self.assertEqual(out.reported_observations["risk_score"], 72)
        self.assertTrue(out.retrieval_hints)
        self.assertEqual(out.model_generated_conclusions, ())
        self.assertIn("not a probability", out.event.attributes["semantic_caveats"]["risk_score"])

    def test_malformed_payload_falls_back_only_with_raw_record(self):
        out = normalize_llm_payload("not-json", tenant_id="t", source_instance="s", raw_record={"notable_id":"N-1","_time":"2026-01-01T00:00:00Z"}, observed_at="2026-01-01T01:00:00Z")
        self.assertIn("malformed_llm_payload", out.warnings)
        with self.assertRaises(NormalizationError):
            normalize_llm_payload("not-json", tenant_id="t", source_instance="s")

    def test_nested_ocsf_preserves_distinct_source_ids(self):
        row = next(item for item in self.dataset["records"] if item["scenario"] == "nested_ocsf_envelope")
        out = normalize_llm_payload(row["llm_payload"], tenant_id=row["tenant_id"], source_instance=row["source_instance"], raw_record=row["raw_record"], observed_at="2026-10-31T00:00:00Z")
        ids = out.verified_source_metadata["identifiers"]
        self.assertEqual(ids["notable_id"], "NOTABLE-OCSF-001")
        self.assertEqual(ids["source_event_id"], "EVENT-OCSF-001")

    def test_delivery_replay_has_stable_source_checksum(self):
        payload = {"alert_id":"NOTABLE-1", "event_time":"2026-01-01T00:00:00Z", "alert_time":"2026-01-01T00:01:00Z"}
        raw = {"notable_id":"NOTABLE-1", "source_event_id":"EVENT-1", "rule_id":"RULE-1"}
        first = normalize_llm_payload(payload, tenant_id="t", source_instance="s", raw_record=raw, observed_at="2026-01-01T01:00:00Z", delivery_id="d-1")
        replay = normalize_llm_payload(payload, tenant_id="t", source_instance="s", raw_record=raw, observed_at="2026-01-02T01:00:00Z", delivery_id="d-2")
        self.assertEqual(first.event.content_checksum, replay.event.content_checksum)
        self.assertEqual(first.event.observed_at, "2026-01-01T00:01:00.000000Z")
        self.assertNotEqual(first.event.recorded_at, replay.event.recorded_at)

    def test_agentic_alert_envelope_keeps_alert_notable_event_and_rule_distinct(self):
        raw = {
            "id":"SOC-ROW-1",
            "alert": {
                "notable_id":"NOTABLE-1", "source_event_ids":["EVENT-1", "EVENT-2"],
                "rule_id":"RULE-1", "_time":"2026-01-01T00:00:00Z",
            },
        }
        out = normalize_llm_payload({"alert_id":"NOTABLE-1", "event_time":"2026-01-01T00:00:00Z"}, tenant_id="t", source_instance="s", raw_record=raw, observed_at="2026-01-01T01:00:00Z")
        by_type = {}
        for entity in out.event.entities:
            by_type.setdefault(entity.entity_type, []).append(entity)
        self.assertEqual(out.event.event_type, "security_alert")
        self.assertEqual(out.event.source_record_id, "SOC-ROW-1")
        self.assertEqual(len(by_type["SecurityAlert"]), 1)
        self.assertEqual(len(by_type["SplunkNotable"]), 1)
        self.assertEqual(len(by_type["SecurityEvent"]), 2)
        self.assertEqual(len(by_type["DetectionRule"]), 1)
        self.assertIn("CORRELATED_WITH", {relation.relation_type for relation in out.event.relations})
        self.assertIn("SUPPORTED_BY", {relation.relation_type for relation in out.event.relations})
        self.assertIn("DETECTED_BY", {relation.relation_type for relation in out.event.relations})

    def test_rule_name_is_provisional_and_index_is_not_network_scope(self):
        raw = {"notable_id":"N-1", "_time":"2026-01-01T00:00:00Z", "rule_name":"Display only", "src_ip":"10.0.0.8", "index":"security"}
        out = normalize_llm_payload(None, tenant_id="t", source_instance="s", raw_record=raw, observed_at="2026-01-01T01:00:00Z")
        rule = next(entity for entity in out.event.entities if entity.entity_type == "DetectionRule")
        address = next(entity for entity in out.event.entities if entity.entity_type == "IPAddress")
        self.assertTrue(rule.provisional)
        self.assertEqual(rule.source_identifiers, {})
        self.assertTrue(address.provisional)
        self.assertIsNone(address.scope)


if __name__ == "__main__":
    unittest.main()

class SourceRevisionClockTests(unittest.TestCase):
    def test_revisions_keep_occurrence_time_and_advance_only_source_clock(self):
        events=[]
        for hour, status in [('10:00','created'),('10:30','updated'),('11:00','analyst_updated'),('12:00','report_attached')]:
            event=normalize_llm_payload({'alert_id':'N','event_time':'2026-11-05T10:00:00Z'},tenant_id='t',source_instance='s',
                raw_record={'notable_id':'N','source_updated_at':f'2026-11-05T{hour}:00Z','status':status,'source_revision_id':status},
                recorded_at='2026-11-06T00:00:00Z').event
            events.append(event)
        self.assertEqual(len({e.event_time for e in events}),1)
        self.assertEqual([e.observed_at for e in events],sorted(e.observed_at for e in events))
        self.assertEqual(len({e.observed_at for e in events}),4)
        self.assertEqual(len({e.entities[0].entity_id for e in events}),1)
        self.assertEqual(len({e.content_checksum for e in events}),4)

    def test_missing_source_update_does_not_use_delivery_clock_or_opaque_revision(self):
        events=[normalize_llm_payload({'alert_id':'N','event_time':'2026-11-05T10:00:00Z'},tenant_id='t',source_instance='s',
            raw_record={'notable_id':'N','source_revision_id':revision},recorded_at=delivery).event
            for revision,delivery in [('z','2026-11-05T11:00:00Z'),('a','2026-11-06T12:00:00Z')]]
        self.assertEqual(events[0].observed_at,events[1].observed_at)
