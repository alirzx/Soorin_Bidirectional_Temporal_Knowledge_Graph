"""Small reproducible SOC retrieval benchmark (no credentials required)."""

from __future__ import annotations

import json
import math
import statistics
import time

from soorin.contracts import KnowledgeQuery
from soorin.models import DeterministicFakeEmbeddingClient
from soorin.retrieval import DeterministicReranker, RetrievalFoundation, SearchDocument


DOCUMENTS = (
    SearchDocument("d-password-spray", "tenant-blue", "Password spray from 192.0.2.44 affected multiple user accounts MITRE T1110.003", ("NOTABLE-PS-001",), ("splunk:NOTABLE-PS-001",)),
    SearchDocument("d-process", "tenant-blue", "Suspicious PowerShell process on ws01 with encoded command MITRE T1059.001", ("GUID-PROC-001",), ("splunk:GUID-PROC-001",)),
    SearchDocument("d-privileged", "tenant-blue", "Privileged service account activity linked to change ticket CHG-4242", ("NOTABLE-PRIV-001",), ("splunk:NOTABLE-PRIV-001",)),
    SearchDocument("d-other-tenant", "tenant-red", "Password spray from private tenant data", ("SECRET-OTHER",), ()),
)
CASES = (
    ("password spraying authentication failures", {"d-password-spray"}),
    ("PowerShell suspicious process", {"d-process"}),
    ("CHG-4242 privileged account", {"d-privileged"}),
)


def _metrics(ranked: list[str], relevant: set[str], k: int) -> tuple[float, float, float]:
    top = ranked[:k]
    recall = len(set(top) & relevant) / len(relevant)
    reciprocal = next((1.0 / (index + 1) for index, item in enumerate(top) if item in relevant), 0.0)
    dcg = sum((1.0 if item in relevant else 0.0) / math.log2(index + 2) for index, item in enumerate(top))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(relevant), k))) or 1.0
    return recall, reciprocal, dcg / ideal


def run_benchmark(k: int = 3) -> dict:
    modes = {
        "bm25": RetrievalFoundation(DOCUMENTS),
        "bm25_dense_rrf": RetrievalFoundation(DOCUMENTS, DeterministicFakeEmbeddingClient(64)),
        "bm25_dense_rrf_reranker": RetrievalFoundation(DOCUMENTS, DeterministicFakeEmbeddingClient(64), DeterministicReranker()),
    }
    report = {"schema_version": "soorin.soc.retrieval-benchmark.v1", "k": k, "modes": {}}
    for name, engine in modes.items():
        values: list[tuple[float, float, float]] = []
        latencies: list[float] = []
        failures = 0
        for text, relevant in CASES:
            started = time.perf_counter()
            try:
                context = engine.search(KnowledgeQuery("tenant-blue", text, top_k=k))
                ranked = [item["document_id"] for item in context.items]
                values.append(_metrics(ranked, relevant, k))
                failures += context.status == "unavailable"
            except Exception:
                failures += 1
                values.append((0.0, 0.0, 0.0))
            latencies.append((time.perf_counter() - started) * 1000)
        ordered = sorted(latencies)
        p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
        report["modes"][name] = {
            "recall_at_k": statistics.mean(row[0] for row in values),
            "mrr": statistics.mean(row[1] for row in values),
            "ndcg_at_k": statistics.mean(row[2] for row in values),
            "latency_p50_ms": statistics.median(latencies), "latency_p95_ms": ordered[p95_index],
            "failure_rate": failures / len(CASES),
        }
    return report


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), sort_keys=True, indent=2))
