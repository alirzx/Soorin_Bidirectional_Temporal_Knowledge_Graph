from __future__ import annotations

from pathlib import Path
import unittest

from soorin.adapters.splunk import normalize_llm_payload
from soorin.evaluation.graph_integrity import evaluate, load_synthetic_fixture
from soorin.evaluation.retrieval_benchmark import run_benchmark


class EvaluationTests(unittest.TestCase):
    def test_graph_integrity_reports_materialization_inputs_separately(self):
        normalized = normalize_llm_payload(
            {"alert_id":"A-1","alert_time":"2026-01-01T00:00:00Z","event_time":"2026-01-01T00:00:00Z","rule_name":"Synthetic"},
            tenant_id="tenant-a", source_instance="lab", raw_record={"notable_id":"A-1"}, observed_at="2026-01-01T00:01:00Z",
        )
        path = Path(__file__).resolve().parents[2] / "ontology" / "soc_ontology_v1.yaml"
        report = evaluate([normalized.event], ontology_path=path)
        self.assertTrue(report.passed, report.failures)
        self.assertEqual(report.event_count, 1)
        self.assertGreater(report.statement_count, 0)

    def test_retrieval_benchmark_emits_required_metrics(self):
        report = run_benchmark()
        self.assertEqual(set(report["modes"]), {"bm25", "bm25_dense_rrf", "bm25_dense_rrf_reranker"})
        for mode in report["modes"].values():
            self.assertEqual(set(mode), {"recall_at_k", "mrr", "ndcg_at_k", "latency_p50_ms", "latency_p95_ms", "failure_rate"})
            self.assertEqual(mode["failure_rate"], 0)

    def test_labeled_synthetic_fixture_is_loadable(self):
        path = Path(__file__).resolve().parents[1] / "fixtures" / "soc_llm_payload_scenarios_v1.json"
        events = load_synthetic_fixture(path)
        self.assertEqual(len(events), 10)
        self.assertEqual({event.tenant_id for event in events}, {"tenant-blue"})


if __name__ == "__main__":
    unittest.main()
