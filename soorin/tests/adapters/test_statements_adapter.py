from __future__ import annotations

import urllib.error
import unittest

from soorin.adapters.utopia import StatementsAdapter, StatementsClient, StatementsError
from soorin.contracts import CanonicalEntity, KnowledgeRelation, SecurityKnowledgeEvent


def knowledge_event(status="new"):
    alert = CanonicalEntity("alert-key", "SecurityAlert", "A-100")
    host = CanonicalEntity("host-key", "Host", "dc01.example")
    relation = KnowledgeRelation("rel-1", "OBSERVED_ON", alert.entity_id, host.entity_id, valid_from="2026-10-01T10:00:00Z", evidence_ids=("ev-1",))
    return SecurityKnowledgeEvent(
        tenant_id="tenant-a", source_system="splunk", source_instance="lab", source_record_id="A-100",
        event_id="event-a", event_type="security_alert", event_time="2026-10-01T10:00:00Z",
        observed_at="2026-10-01T10:01:00Z", recorded_at="2026-10-01T10:01:00Z",
        entities=(alert, host), relations=(relation,), attributes={"status": status},
    )


class StatementsTests(unittest.TestCase):
    def test_valid_event_renders_exact_contract(self):
        payload = StatementsAdapter().render(knowledge_event())
        self.assertEqual(set(payload), {"external_id", "doc_time", "e", "s", "n"})
        self.assertEqual(payload["s"][0][0], None)
        self.assertEqual(payload["s"][0][2], "observed on")

    def test_replay_and_changed_revision_keep_external_id(self):
        adapter = StatementsAdapter()
        self.assertEqual(adapter.render(knowledge_event())["external_id"], adapter.render(knowledge_event("closed"))["external_id"])
        self.assertNotEqual(adapter.dumps(adapter.render(knowledge_event())), adapter.dumps(adapter.render(knowledge_event("closed"))))

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
