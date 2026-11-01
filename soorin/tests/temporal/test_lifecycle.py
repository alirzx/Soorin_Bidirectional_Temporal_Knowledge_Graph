from __future__ import annotations

import unittest

from soorin.evaluation.temporal_cases import evaluate_temporal_cases
from soorin.temporal import RevisionState, classify_revision


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.previous = RevisionState("A-100", "2026-10-01T10:00:00Z", "2026-10-01T10:01:00Z", "old", "new")

    def test_gold_temporal_cases(self):
        report = evaluate_temporal_cases()
        self.assertTrue(report["passed"], report)
        self.assertEqual(len(report["cases"]), 7)

    def test_identical_replay_creates_no_revision(self):
        decision = classify_revision(self.previous, source_record_id="A-100", event_time="2026-10-01T10:00:00Z", recorded_at="2026-10-01T11:00:00Z", content_checksum="old", status="new")
        self.assertEqual(decision.kind, "exact_replay")
        self.assertFalse(decision.create_revision)

    def test_status_change_closes_previous(self):
        decision = classify_revision(self.previous, source_record_id="A-100", event_time="2026-10-01T10:02:00Z", recorded_at="2026-10-01T10:03:00Z", content_checksum="changed", status="closed")
        self.assertEqual(decision.kind, "state_change")
        self.assertTrue(decision.closes_previous)


if __name__ == "__main__":
    unittest.main()
