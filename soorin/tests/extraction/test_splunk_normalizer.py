from __future__ import annotations

import json
from pathlib import Path
import unittest

from soorin.adapters.splunk.llm_payload_normalizer import NormalizationError, normalize_llm_payload

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "soc_llm_payload_scenarios_v1.json"


class SplunkNormalizerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
