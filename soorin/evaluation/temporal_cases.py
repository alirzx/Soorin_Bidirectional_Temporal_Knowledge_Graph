"""Gold temporal revision cases for offline evaluation."""

from __future__ import annotations

from dataclasses import asdict
import json

from soorin.temporal import RevisionState, classify_revision


def evaluate_temporal_cases() -> dict:
    previous = RevisionState("A-100", "2026-10-01T10:00:00Z", "2026-10-01T10:01:00Z", "old", "new", "r1")
    cases = [
        ("exact_replay", dict(source_record_id="A-100", event_time="2026-10-01T10:00:00Z", recorded_at="2026-10-01T10:02:00Z", content_checksum="old", status="new")),
        ("state_change", dict(source_record_id="A-100", event_time="2026-10-01T10:03:00Z", recorded_at="2026-10-01T10:04:00Z", content_checksum="status", status="investigating")),
        ("correction", dict(source_record_id="A-100", event_time="2026-10-01T10:03:00Z", recorded_at="2026-10-01T10:04:00Z", content_checksum="fix", status="new")),
        ("late_arrival", dict(source_record_id="A-100", event_time="2026-09-30T10:00:00Z", recorded_at="2026-10-01T10:05:00Z", content_checksum="late", status="new")),
        ("new_occurrence", dict(source_record_id="A-101", event_time="2026-10-01T10:03:00Z", recorded_at="2026-10-01T10:04:00Z", content_checksum="new", status="new")),
        ("retraction", dict(source_record_id="A-100", event_time="2026-10-01T10:03:00Z", recorded_at="2026-10-01T10:04:00Z", content_checksum="ret", status="new", explicit_action="retraction")),
        ("supersession", dict(source_record_id="A-100", event_time="2026-10-01T10:03:00Z", recorded_at="2026-10-01T10:04:00Z", content_checksum="sup", status="new", explicit_action="supersession")),
    ]
    results = []
    for expected, args in cases:
        actual = classify_revision(previous, **args)
        results.append({"expected": expected, "actual": actual.kind, "passed": expected == actual.kind, "decision": asdict(actual)})
    return {"schema_version": "soorin.soc.temporal-evaluation.v1", "passed": all(row["passed"] for row in results), "cases": results}


if __name__ == "__main__":
    print(json.dumps(evaluate_temporal_cases(), sort_keys=True, indent=2))
