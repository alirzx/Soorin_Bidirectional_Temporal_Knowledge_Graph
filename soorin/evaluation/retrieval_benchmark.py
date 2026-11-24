"""Small reproducible SOC retrieval benchmark (no credentials required)."""

from __future__ import annotations

import json
import math
import platform
import statistics
import sys
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
# Hard negatives share vocabulary with the judged incidents. Keep the corpus
# larger than the largest cutoff so recall@10 can actually miss a relevant alert.
DISTRACTORS = (
    "Password rotation completed for a privileged service account",
    "PowerShell system inventory started by a scheduled task",
    "Multiple accounts completed authentication after a password reset",
    "Change ticket linked to privileged account creation",
    "Process inspection on ws01 completed successfully",
    "Encoded attachment scanned by mail gateway",
    "Failed authentication on one expired test account",
    "Suspicious process activity on an unrelated workstation",
    "Service account access reviewed at quarter end",
    "PowerShell execution policy changed by administrator",
)
DOCUMENTS += tuple(SearchDocument(f"control-{i}", "tenant-blue", text)
                   for i, text in enumerate(DISTRACTORS))
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
    report = {
        "schema_version": "soorin.soc.retrieval-benchmark.v1",
        "dataset": {
            "name": "soorin-synthetic-retrieval", "version": "v2", "synthetic": True,
            "document_count": len(DOCUMENTS), "query_count": len(CASES),
        },
        "reproducibility": {
            "deterministic": True, "random_seed": None,
            "python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": platform.platform(), "machine": platform.machine(),
            "executable": sys.executable,
        },
        "k": k,
        "modes": {},
    }
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


def quality_at_cutoffs() -> dict:
    """Binary document qrels, macro averages. CPU weights are never loaded."""
    at5, at10 = run_benchmark(5)["modes"], run_benchmark(10)["modes"]
    report = {name: {"recall5": at5[name]["recall_at_k"], "recall10": row["recall_at_k"],
                     "mrr10": row["mrr"], "ndcg10": row["ndcg_at_k"]} for name, row in at10.items()}
    dense = RetrievalFoundation(DOCUMENTS, DeterministicFakeEmbeddingClient(64))
    eligible = [d for d in DOCUMENTS if d.tenant_id == "tenant-blue"]
    scores = []
    for text, relevant in CASES:
        ranked = [doc.document_id for doc, _ in dense._dense(eligible, text, 10)]
        scores.append((_metrics(ranked, relevant, 5)[0], *_metrics(ranked, relevant, 10)))
    report["dense_only_mock"] = dict(zip(("recall5","recall10","mrr10","ndcg10"),
                                         map(statistics.mean, zip(*scores))))
    return report


def rerank_window_benchmark() -> dict:
    """Synthetic rank-boundary and padded-token workload model."""
    queries = [
        ("password spray", "password spray across directory accounts", 7),
        ("encoded powershell", "encoded powershell process", 12),
        ("privileged ticket", "privileged ticket linked to service user", 15),
    ]
    windows = (8, 12, 16, 24, 48)
    quality = {}
    for window in windows:
        samples = []
        for query, positive, positive_rank in queries:
            doc_ids = [f"doc-{i}" for i in range(48)]
            documents = ["routine synthetic sensor message"] * 48
            documents[positive_rank] = positive
            terms = set(query.split())
            ranking = sorted(range(window), key=lambda i: -len(terms & set(documents[i].split())))
            ranking += list(range(window, len(documents)))
            samples.append(_metrics([doc_ids[i] for i in ranking], {doc_ids[positive_rank]}, 10))
        quality[window] = dict(zip(("recall10", "mrr10", "ndcg10"), map(statistics.mean, zip(*samples))))

    # Simulated tokenized pair lengths, capped at 512. The relative work proxy
    # includes padding within each group of four in Engine.predict, plus wire calls.
    lengths = (74, 160, 290, 512, 100, 175, 410, 244) * 6
    costs = {}
    for window in windows:
        costs[window] = {}
        for batch in (4, 8, 16):
            groups = [lengths[i:min(i+batch, window)] for i in range(0, window, batch)]
            padded_tokens = sum(len(group[i:i+4])*max(group[i:i+4])
                                for group in groups for i in range(0, len(group), 4))
            costs[window][batch] = {"requests": len(groups), "padded_tokens": padded_tokens}
    return {"quality": quality, "workload_model": costs}


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), sort_keys=True, indent=2))
