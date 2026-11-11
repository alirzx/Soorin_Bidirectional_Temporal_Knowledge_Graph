from __future__ import annotations

import json
import hashlib
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from soorin.contracts import (
    CanonicalEntity, ContractError, KnowledgeRelation, SecurityKnowledgeEvent,
    EvidenceReference, LEGACY_CHECKSUM_VERSION, SOURCE_CONTENT_CHECKSUM_V2,
    SOURCE_CONTENT_CHECKSUM_VERSION, TemporalFact, validate_event_batch,
)
from soorin.contracts.knowledge_event_v1 import canonical_json


def event(**changes):
    entity = CanonicalEntity("entity-1", "Host", "dc01.lab.example")
    values = dict(
        tenant_id="tenant-a", source_system="splunk", source_instance="lab",
        source_record_id="record-1", event_id="event-1", event_type="notable",
        event_time="2026-10-01T12:00:00+03:30", observed_at="2026-10-01T09:00:01Z",
        recorded_at="2026-10-01T09:00:02Z", entities=(entity,),
    )
    values.update(changes)
    return SecurityKnowledgeEvent(**values)


class KnowledgeEventTests(unittest.TestCase):
    def test_serialization_is_deterministic_and_utc(self):
        left = event(attributes={"b": 2, "a": 1})
        right = event(attributes={"a": 1, "b": 2})
        self.assertEqual(left.to_json(), right.to_json())
        self.assertEqual(left.event_time, "2026-10-01T08:30:00.000000Z")
        self.assertEqual(len(left.content_checksum), 64)

    def test_round_trip_and_vendor_fields(self):
        original = event(vendor_fields={"future_vendor_field": {"x": 1}})
        self.assertEqual(SecurityKnowledgeEvent.from_json(original.to_json()), original)

    def test_malformed_json_and_unknown_contract_field(self):
        with self.assertRaisesRegex(ContractError, "malformed_json"):
            SecurityKnowledgeEvent.from_json("{")
        data = event().to_dict() | {"silent_vendor_field": 1}
        with self.assertRaisesRegex(ContractError, "unknown_contract_field"):
            SecurityKnowledgeEvent.from_dict(data)

    def test_missing_tenant_and_naive_timestamp(self):
        data = event().to_dict()
        del data["tenant_id"]
        with self.assertRaisesRegex(ContractError, "missing_required_field"):
            SecurityKnowledgeEvent.from_dict(data)
        with self.assertRaisesRegex(ContractError, "timezone_required"):
            event(event_time="2026-10-01T08:30:00")

    def test_invalid_entity_references(self):
        relation = KnowledgeRelation("r1", "OBSERVED_ON", "entity-1", "missing")
        with self.assertRaisesRegex(ContractError, "invalid_entity_reference"):
            event(relations=(relation,))
        fact = TemporalFact("f1", "missing", "has status", "2026-10-01T09:00:00Z", object_value="new")
        with self.assertRaisesRegex(ContractError, "invalid_entity_reference"):
            event(facts=(fact,))

    def test_oversized_payload_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "payload_too_large"):
            event(vendor_fields={"raw": "x" * (1024 * 1024)})

    def test_duplicate_batch_distinguishes_replay_and_revision(self):
        first = event()
        replay = event()
        changed = event(attributes={"status": "closed"})
        rows = validate_event_batch([first, replay, changed])
        self.assertEqual([row.disposition for row in rows], ["exact_replay", "changed_revision"])

    def test_checksum_tampering_is_rejected(self):
        data = event().to_dict()
        data["content_checksum"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "checksum_mismatch"):
            SecurityKnowledgeEvent.from_dict(data)

    def test_source_checksum_ignores_delivery_and_processing_time(self):
        left = event(recorded_at="2026-10-01T09:00:02Z", processed_at="2026-10-01T09:00:03Z", delivery_id="delivery-a")
        right = event(recorded_at="2026-10-02T09:00:02Z", processed_at="2026-10-02T09:00:03Z", delivery_id="delivery-b")
        self.assertEqual(left.content_checksum_version, SOURCE_CONTENT_CHECKSUM_VERSION)
        self.assertEqual(left.content_checksum, right.content_checksum)

    def test_source_checksum_changes_for_source_revision_and_observation(self):
        baseline = event(source_revision_id="1")
        revised = event(source_revision_id="2")
        later_source_observation = event(source_revision_id="1", observed_at="2026-10-01T09:01:01Z")
        self.assertNotEqual(baseline.content_checksum, revised.content_checksum)
        self.assertNotEqual(baseline.content_checksum, later_source_observation.content_checksum)

    def test_v3_checksum_and_json_are_order_independent_for_set_like_collections(self):
        entities = (
            CanonicalEntity("entity-1", "Host", "dc01", aliases=("DC01", "dc01")),
            CanonicalEntity("entity-2", "User", "alice"),
        )
        evidence = (
            EvidenceReference("ev-2", "record-1", source_event_ids=("b", "a")),
            EvidenceReference("ev-1", "record-1"),
        )
        relations = (
            KnowledgeRelation("r-2", "OBSERVED_ON", "entity-2", "entity-1", evidence_ids=("ev-2", "ev-1")),
            KnowledgeRelation("r-1", "RELATED_TO", "entity-1", "entity-2", evidence_ids=("ev-1",)),
        )
        left = event(
            entities=entities, evidence=evidence, relations=relations,
            source_references=("z", "a"),
        )
        right = event(
            entities=tuple(reversed(entities)), evidence=tuple(reversed(evidence)),
            relations=tuple(reversed(relations)), source_references=("a", "z"),
        )
        self.assertEqual(left.content_checksum, right.content_checksum)
        self.assertEqual(left.to_json(), right.to_json())

    def test_v2_keeps_legacy_order_sensitive_algorithm(self):
        first = CanonicalEntity("entity-1", "Host", "dc01")
        second = CanonicalEntity("entity-2", "Host", "dc02")
        left = event(entities=(first, second), content_checksum_version=SOURCE_CONTENT_CHECKSUM_V2)
        right = event(entities=(second, first), content_checksum_version=SOURCE_CONTENT_CHECKSUM_V2)
        self.assertNotEqual(left.content_checksum, right.content_checksum)

    def test_duplicate_ids_and_unknown_evidence_are_rejected(self):
        relation = KnowledgeRelation("r1", "OBSERVED_ON", "entity-1", "entity-1", evidence_ids=("missing",))
        with self.assertRaisesRegex(ContractError, "invalid_evidence_reference"):
            event(relations=(relation,))
        duplicate = EvidenceReference("ev-1", "record-1")
        with self.assertRaisesRegex(ContractError, "duplicate_evidence"):
            event(evidence=(duplicate, duplicate))

    def test_fact_confidence_is_the_same_closed_vocabulary_as_relations(self):
        with self.assertRaisesRegex(ContractError, "invalid_confidence_category"):
            TemporalFact(
                "f1", "entity-1", "has status", "2026-10-01T09:00:00Z",
                object_value="new", confidence_category="certain-ish",
            )

    def test_representative_serialization_validates_against_published_schema(self):
        evidence = EvidenceReference(
            "ev-1", "record-1", source_system="splunk", source_instance="lab",
            source_event_ids=("source-event-1",), source_revision_id="7",
        )
        relation = KnowledgeRelation(
            "r1", "OBSERVED_ON", "entity-1", "entity-1", evidence_ids=("ev-1",),
        )
        instance = event(evidence=(evidence,), relations=(relation,)).to_dict()
        schema_path = Path(__file__).parents[2] / "contracts" / "schemas" / "knowledge_event_v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance))
        self.assertEqual(errors, [], [error.message for error in errors])

    def test_legacy_checksum_is_verified_without_rehashing(self):
        data = event().to_dict()
        for key in ("source_revision_id", "delivery_id", "processed_at", "content_checksum_version", "content_checksum"):
            data.pop(key, None)
        legacy_hash = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
        data["content_checksum"] = legacy_hash
        restored = SecurityKnowledgeEvent.from_dict(data)
        self.assertEqual(restored.content_checksum_version, LEGACY_CHECKSUM_VERSION)
        self.assertEqual(restored.content_checksum, legacy_hash)


if __name__ == "__main__":
    unittest.main()
