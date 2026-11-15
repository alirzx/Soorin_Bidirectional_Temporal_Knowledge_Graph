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

## Continuation acceptance fixtures (2026-11-15)

The native harness checks every expected relation as a multiset of predicate,
subject and object, plus document/version evidence, type binding, source scope,
authority links and idempotent receipt replay. It stops dependent API checks after
a failed prerequisite and reports their BLOCKED status. It performs no broad
requeue. `--with-cpu-models` enables explicit dense/BM25/reranker execution checks;
execution is distinct from relevance. The live harness was NOT RUN in this pass.

`soc_native_materialization_v1.json` contains three canonical synthetic events,
including a new same-record revision and repeated reviewed signature. The Rust
API regression drives the existing pipeline/alignment/materializer and diagnostic
gates. Job writeback regressions own their rows and inject a persistence failure;
they do not launch a global worker against another test's queue.

`soc_retrieval_acceptance_v1.json` versions eight bilingual/exact/no-result/
tenant/temporal/evidence cases. Its unit evaluator uses lexical retrieval only;
existing benchmark ablations use fake vectors. Neither proves BGE relevance.
SearchDocument timestamps are normalized and current results exclude invalidated
versions; the knowledge-time boundary is half open. Production ranking, genuine
BGE/reranker scores, NER precision/recall/latency/RAM and live Agent grounding
remain separate controlled tests.

Read-scope MCP exposes the eleven names in `mcp.rs::EXPOSED`. The existing
`remember` proposal tool is additionally exposed only when PAT write scope and
KB editor role both permit it. It is not included in read-only investigation PATs.
A 401 without a proven valid PAT remains an authentication result, not evidence
of a broken MCP server.
