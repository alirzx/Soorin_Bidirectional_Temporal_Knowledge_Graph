# Testing and evaluation

Use [Pre-build validation](PREBUILD_VALIDATION.md) for lightweight checks and
[Build and test handoff](BUILD_AND_TEST_HANDOFF.md) for deferred runtime stages.
[Acceptance report](FINAL_ACCEPTANCE_REPORT.md) distinguishes current evidence
from earlier CI and real-model results.

Synthetic corpora cover normalization/source IDs, tenant/network isolation,
canonical checksums, ontology integrity, temporal classification, grounded citations,
model contracts, privacy and retries. Run graph integrity against
`soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json`; temporal classification
via `python3 -m soorin.evaluation.temporal_cases`. These are contract/lifecycle
checks, not a deployed bitemporal database test.

`soorin.evaluation.retrieval_benchmark` uses four documents, three queries and
fake providers. It reports recall@K, MRR, nDCG, failure rate and p50/p95 latency.
Do not report these as BGE, native Rust retrieval or real reranker measurements.
Native acceptance needs bilingual relevance labels, temporal holdout, duplicate
and entity leakage analysis, exact identifier baselines, current/historical query
pairs and cross-tenant negative cases. Save dataset/config hashes, model revision,
metrics, hardware and failed examples; synthetic latency does not predict deployment.

Routine CI runs Rust formatting/Clippy/tests/build, migrations, Python and frontend;
backend aggregation now includes all required jobs. Real model downloads/inference
remain outside routine CI. Release requires latest exact-commit CI success and a
configured protected release environment. Never weaken assertions or count skipped
DB/model tests as passes.
