# Continuation task matrix — 2026-11-15

Scope: source review and lightweight offline validation. Local compilation,
container startup, migration execution, model inference and live E2E were not run.
The initial baseline is b98b0c4; five previously published patches end at efee3b2.
Statuses below describe full task acceptance, including required runtime gates.
Core automatic CI is green at b83e4c3; final-HEAD CI is reported separately after
publishing the final continuation commit. CI is not full deployment acceptance.

| Task | Status | Files / tests reviewed or added | Remaining runtime verification |
|---|---|---|---|
| TKG-01 Scheduling / leases | IMPLEMENTED_NOT_VERIFIED | `soc_ingestion.rs`, `jobs.rs`; Deferred/expiry/owner tests; claim-fenced acknowledgement | Three concurrent same-source receipts, independent sources, actual cancellation/restart |
| TKG-02 Materialization lifecycle | IMPLEMENTED_NOT_VERIFIED | Shared receipt gates; terminal predecessor/document classification; CI native pipeline regression | Faults at registered/submitted transitions, downstream retry timing |
| TKG-03 Typed relations / evidence | IMPLEMENTED_NOT_VERIFIED | `soc_alignment.rs`, shared `relation_status`; current-version typed evidence and entity gates | Full image, human rejection, temporal history and source revisions under live workers |
| TKG-04 CPU models | IMPLEMENTED_NOT_VERIFIED | Pinned-only BGE windows; generic provider preservation; bounded inference/parser threads; mock tests | Real concurrent inference, 1024-dimension smoke, quality/RAM/latency/cache restart |
| TKG-05 Recovery / diagnostics | IMPLEMENTED_NOT_VERIFIED | `jobs_writeback_tests.rs`, receipt diagnostics; CI DB fault injection and stale-claim tests | Runtime DB outage/restart and targeted operator recovery |
| TKG-06 Native E2E | IMPLEMENTED_NOT_VERIFIED | Exact predicate/endpoints/version/source assertions; session bootstrap; unit tests | Ownership-gated live harness, deterministic then CPU mode |
| TKG-07 QA configuration | COMPLETE | Make password expansion/RNG failure/noclobber; temporary-file tests; quiet Compose validation | Config correctness does not imply startup acceptance |
| TKG-08 Producer contracts | COMPLETE | Read-only a0a160d review; versioned producer mapping and synthetic fixtures | Live producer/Agentic_SOC integration remains unexecuted |
| TKG-09 Entity extraction | COMPLETE | Nested/mixed arrays, typed fusion values, local hints, nested scope and encoded JSON; unit regressions | Real payload sampling/relevance remains qualification work |
| TKG-10 Identity / authority | IMPLEMENTED_NOT_VERIFIED | Existing canonical registry, source/tenant/authority/network tests; diagnostic link checks | Live exact resolution, conflict/race behavior with actual source set |
| TKG-11 Relation generation | IMPLEMENTED_NOT_VERIFIED | Existing reviewed ontology, native profile; three-event typed materialization fixture | All supported producer signatures through runtime workers |
| TKG-12 Curated HTTP | IMPLEMENTED_NOT_VERIFIED | `soc_curated.rs`, stdlib subprocess, preview/native replay tests, OpenAPI | Built nonroot/read-only image, child cancellation/timeouts/peak memory |
| TKG-13 Temporal / replay | BLOCKED_BY_RUNTIME_TEST | Source clocks/quarantine; CI graph revision tests; offline half-open boundary fix | Historical evidence attachment, restart and out-of-order live revision matrix |
| TKG-14 Retrieval / GraphRAG | BLOCKED_BY_RUNTIME_TEST | Versioned bilingual/exact/no-result/tenant/history/evidence cases; fake-vector benchmark | Real relevance metrics, dense/reranker ablation and grounded live citations |
| TKG-15 NER review | BLOCKED_BY_RUNTIME_TEST | Injected CPU NER / proposal-only / unsupported-script tests | Actual pinned-model precision/recall/FP/FN/latency/RAM |
| TKG-16 MCP | BLOCKED_BY_RUNTIME_TEST | Existing authenticated PAT/KB/tool/read-only CI tests; eleven read tools reviewed | Valid/revoked/wrong-KB live PAT and tools/call |
| TKG-17 Chat / native Agent | BLOCKED_BY_EXTERNAL_CONFIGURATION | Configurable endpoint/model/key/idle timeout; URL/secret guard; gateway/agent mock tests | Actual approved credentials/model/tenant map/gateway; provider and agent acceptance |
| TKG-18 Deployment | IMPLEMENTED_NOT_VERIFIED | Python stdlib runtime, UID 65532, private production models/DB; 105 migrations; static Compose | Image qualification, migration owner/runtime grants, TLS/CORS and restore drill |
| TKG-19 Release acceptance | BLOCKED_BY_RUNTIME_TEST | Schema CI fixed; automatic core CI evidence; complete next-session runbook | Exact final-image local build and all runtime gates; FULL_E2E_VERIFIED=false |

Details: [continuation report](CONTINUATION_HARDENING_REPORT.md),
[verified call paths](CONTINUATION_ARCHITECTURE.md),
[next approved session](NEXT_APPROVED_BUILD_20261115.md).
