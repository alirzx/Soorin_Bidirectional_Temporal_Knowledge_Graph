from __future__ import annotations

import urllib.error
import unittest
from dataclasses import replace

from soorin.adapters.utopia import StatementsAdapter, StatementsClient, StatementsError
from soorin.contracts import CanonicalEntity, EvidenceReference, KnowledgeRelation, SecurityKnowledgeEvent, TemporalFact


def knowledge_event(status="new"):
    alert = CanonicalEntity("alert-key", "SecurityAlert", "A-100")
    host = CanonicalEntity("host-key", "Host", "dc01.example")
    relation = KnowledgeRelation("rel-1", "OBSERVED_ON", alert.entity_id, host.entity_id, valid_from="2026-10-01T10:00:00Z", evidence_ids=("ev-1",))
    return SecurityKnowledgeEvent(
        tenant_id="tenant-a", source_system="splunk", source_instance="lab", source_record_id="A-100",
        event_id="event-a", event_type="security_alert", event_time="2026-10-01T10:00:00Z",
        observed_at="2026-10-01T10:01:00Z", recorded_at="2026-10-01T10:01:00Z",
        entities=(alert, host), relations=(relation,), attributes={"status": status},
        evidence=(EvidenceReference(
            "ev-1", "A-100", field_path="llm_payload.src_ip", source_uri="splunk://notable/A-100",
            checksum="abc123", observed_at="2026-10-01T10:00:00Z", source_system="splunk",
            source_instance="lab", source_event_ids=("EVENT-1",), source_revision_id="7",
        ),),
    )


class StatementsTests(unittest.TestCase):
    def test_valid_event_renders_exact_contract(self):
        payload = StatementsAdapter().render(knowledge_event())
        self.assertEqual(set(payload), {"external_id", "doc_time", "e", "s", "n"})
        self.assertEqual(payload["s"][0][0], None)
        self.assertEqual(payload["s"][0][2], "observed on")

    def test_evidence_metadata_is_recoverable_without_raw_logs(self):
        payload = StatementsAdapter().render(knowledge_event())
        evidence_entity = next(row[0] for row in payload["e"] if row[1] == "EvidenceReference")
        facts = {row[2]: row[4] for row in payload["s"] if row[1] == evidence_entity and row[4] is not None}
        self.assertEqual(facts["has evidence id"], "ev-1")
        self.assertEqual(facts["has source system"], "splunk")
        self.assertEqual(facts["has source instance"], "lab")
        self.assertEqual(facts["has source record id"], "A-100")
        self.assertEqual(facts["has source event ids"], '["EVENT-1"]')
        self.assertEqual(facts["has source field path"], "llm_payload.src_ip")
        self.assertEqual(facts["has source URI"], "splunk://notable/A-100")
        self.assertEqual(facts["has source checksum"], "abc123")
        self.assertTrue(any(row[1] == "alert-key" and row[2] == "supported by" and row[3] == evidence_entity for row in payload["s"]))

    def test_replay_and_changed_revision_keep_external_id(self):
        adapter = StatementsAdapter()
        self.assertEqual(adapter.render(knowledge_event())["external_id"], adapter.render(knowledge_event("closed"))["external_id"])
        self.assertNotEqual(adapter.dumps(adapter.render(knowledge_event())), adapter.dumps(adapter.render(knowledge_event("closed"))))

    def test_delivery_metadata_does_not_mutate_statements(self):
        adapter = StatementsAdapter()
        event = knowledge_event()
        replay = replace(
            event, recorded_at="2026-10-02T11:12:13Z",
            processed_at="2026-10-02T11:12:14Z", delivery_id="retry-12",
        )
        self.assertEqual(event.content_checksum, replay.content_checksum)
        self.assertEqual(adapter.dumps(adapter.render(event)), adapter.dumps(adapter.render(replay)))

    def test_document_type_is_in_v2_identity_and_v1_remains_available(self):
        adapter = StatementsAdapter()
        event = knowledge_event()
        other_kind = replace(event, event_type="splunk_notable", content_checksum=None)
        self.assertNotEqual(adapter.external_id(event), adapter.external_id(other_kind))
        self.assertEqual(StatementsAdapter(external_id_version="v1").external_id(event),
            StatementsAdapter(external_id_version="v1").external_id(other_kind))
        with self.assertRaises(StatementsError):
            StatementsAdapter(external_id_version="unknown").external_id(event)

    def test_v2_statements_are_order_independent_and_preserve_all_evidence_ids(self):
        base = knowledge_event()
        ev2 = EvidenceReference("ev-2", "A-100", source_event_ids=("EVENT-2",))
        relation = replace(base.relations[0], evidence_ids=("ev-2", "ev-1"))
        fact = TemporalFact(
            "fact-1", "alert-key", "has status", "2026-10-01T10:01:00Z",
            object_value="new", evidence_ids=("ev-1", "ev-2"),
        )
        left = replace(
            base, evidence=(base.evidence[0], ev2), relations=(relation,), facts=(fact,),
            content_checksum=None,
        )
        right = replace(
            base, entities=tuple(reversed(base.entities)), evidence=(ev2, base.evidence[0]),
            relations=(relation,), facts=(fact,), content_checksum=None,
        )
        adapter = StatementsAdapter()
        left_payload = adapter.render(left)
        right_payload = adapter.render(right)
        self.assertEqual(adapter.dumps(left_payload), adapter.dumps(right_payload))
        relation_row = next(row for row in left_payload["s"] if row[2] == "observed on")
        self.assertEqual(relation_row[5]["evidence_id"], "ev-1")
        self.assertEqual(relation_row[5]["evidence_ids"], '["ev-1","ev-2"]')

    def test_v1_external_identity_uses_exact_historical_pipe_hash(self):
        event = knowledge_event()
        expected = "soorin-soc-v1:tenant-a:" + __import__("hashlib").sha256(
            "tenant-a|splunk|lab|A-100".encode("utf-8")
        ).hexdigest()[:24]
        self.assertEqual(StatementsAdapter(external_id_version="v1").external_id(event), expected)

    def test_statement_count_and_size_limits(self):
        adapter = StatementsAdapter(max_statements=1)
        with self.assertRaisesRegex(StatementsError, "invalid_statement_count"):
            adapter.render(knowledge_event())
        with self.assertRaisesRegex(StatementsError, "payload_too_large"):
            StatementsAdapter(max_bytes=100).render(knowledge_event())

    def test_success_response_validation(self):
        client = StatementsClient("http://test", "source", "token", transport=lambda request, timeout: {"action": "created"})
        self.assertEqual(client.push(StatementsAdapter().render(knowledge_event())), "created")
        client.transport = lambda request, timeout: {"unexpected": True}
        with self.assertRaisesRegex(StatementsError, "malformed_api_response"):
            client.push(StatementsAdapter().render(knowledge_event()))

    def test_timeout_is_structured(self):
        def timeout(request, seconds):
            raise TimeoutError("slow")
        with self.assertRaisesRegex(StatementsError, "api_timeout"):
            StatementsClient("http://test", "source", "token", transport=timeout).push(StatementsAdapter().render(knowledge_event()))


if __name__ == "__main__":
    unittest.main()
