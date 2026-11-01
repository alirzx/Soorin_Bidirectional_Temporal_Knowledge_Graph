# Soorin SOC foundation · Gap analysis and release gates

**Status:** Sprint 1 contracts and offline Python foundation exist, but the feature branch is **not approved for production or merge**. This document distinguishes a real implementation from an offline-only proof.

## Verified Sprint 1 deliverables

- Versioned `soorin.soc.knowledge-event.v1` contracts and JSON Schema; deterministic serialization and synthetic fixtures.
- SOC ontology declaration: 17 entity types and 15 relation types; dry-run/guarded importer using mock API tests.
- Canonical key generation, normalization, provisional decisions and conservative identity policy.
- Field-aware security entity extraction; optional NER **interface only**.
- Splunk/Agentic SOC `llm_payload` normalization and Utopia Statements rendering/transport adapters.
- Alert revision classification and domain-time mapping tests **without live KB revision validation**.
- Python model profiles, Chat readiness/embedding adapters, provider-specific reranker adapters and offline retrieval/benchmark.
- Reported tests: 61 Python foundation, 7 baseline synthetic lab, 268 React UI, isolated Compose syntax and synthetic evaluation. See [Implementation report](SPRINT1_IMPLEMENTATION_REPORT.md) for exact evidence.

## P0 · Correctness/security issues to resolve before live SOC data

| ID | Problem observed in feature-branch source | Required proof |
| --- | --- | --- |
| S1-P0-01 | Normalizer defaults `observed_at`/`recorded_at` to processing time, and source-event checksum includes it. Same source event may appear as a changed revision on replay. | Replay at different ingest times yields stable source-content identity; true revision remains detectable. |
| S1-P0-02 | `llm_payload_normalizer` always creates a `SplunkNotable` anchor, even for event-only input or SOC Alert IDs. | Distinct Event / Notable / SOC Alert identities, each mapped from authoritative IDs, with tested relationships. |
| S1-P0-03 | In-memory canonical key functions are not a persistent TKG identity registry. Splunk `index` must not be assumed to identify a network scope. | Stable ID across documents, tenant/network collision tests in persisted Utopia graph. |
| S1-P0-04 | Ontology importer comparison mostly checks labels/temporal type; domain/range and remaining semantic constraints can diverge undetected. | Full-diff, conflict refusal, and isolated-KB import verification. |
| S1-P0-05 | Statements adapter does not project all `EvidenceReference` metadata into recoverable evidence structure. | Evidence locator, source field, checksum and timestamp are round-trippable. |
| S1-P0-06 | `SOORIN_*` model variables are Python-only in the current checkout; they do **not** configure live Utopia Rust. | Actual Workspace Settings connection tests, embedding dimension and alignment; correct docs/config. |
| S1-P0-07 | Semantic-text filtering by secret-looking keys is not a complete DLP/privacy boundary. | Approved privacy routing for any real SOC content sent to external model/embedding endpoints. |
| S1-P0-08 | Live Utopia revision, `at`/`as_of`, typed materialization and actual Graph API results are unverified. | Disposable KB/source integration tests with expected historical results and graph counts. |
| S1-P0-09 | Cargo fmt/check/test were blocked by absent toolchain/image availability. | Rust checks pass on a supported host or CI before merge. |

## P1 · Integration, accuracy and scalability

- Native Rust retrieval/reranker integration, authenticated configuration persistence and React UI; Python's in-memory search is a **reference/evaluation implementation**, not a production search service.
- Do not embed every eligible document on every query; use existing Utopia pgvector indexes, bounded candidates and scalable re-ranking.
- Implement a real optional SOC NER model only if deterministic extraction + validated model enrichment is required.
- Verify authoritative DetectionRule identifiers; display-only `rule_name` is not equivalent to a stable rule ID.
- Version-aware historical Tantivy retrieval: current index can filter current hits for `as_of` but cannot recall replaced historical chunks.
- Limit Python embedding cache growth; expose resource budgets, timeout/retry metrics and useful provider diagnostics.
- Replace ontology CLI `--token` process arguments with protected input/environment handling before operational use.
- Build and health-test the isolated Soorin source image on ports `2516`/`2517`; do not overwrite rc9 lab `1516`/`1517`.

## Not yet in scope: future Agentic SOC integrations

The live Splunk/Kafka consumer, SOC PostgreSQL backfill, Agentic SOC Auto-Triage/Copilot/Investigator reads, tenant-to-KB authorization, Privacy Gateway integration, report/case write-back, operational monitoring and production deployment remain later sprint work.

**Release decision:** Keep `feature/soc-knowledge-foundation-v1` separate from `main` until P0 code hardening, isolated live Utopia acceptance, real model verification and Rust regression gates are complete. Offline evaluation metrics are not production accuracy evidence.


## November 2026 hardening review · current implementation status

The original Sprint 1 P0 table above is a **historical baseline**. The branch now includes four hardening commits (`b321fd0`, `c296cbd`, `af4be6e`, `0a3e48e`) and two WIP commits (`b386dc3`, `99fee1d`). Previous issues must not be reported as wholly unresolved without acknowledging these changes. This review is source-based; no real PostgreSQL migration, Rust compile, or live model test was run here.

### Code delivered but not yet validated

- **Checksum/classification:** source-content checksum excludes delivery/processing time. Splunk Notable, SOC Alert, source Event and Rule IDs are separated in the normalizer. However **rendered Utopia Statements still include delivery/processing/recorded timestamps** and can differ on an unchanged source replay. Confirm `StatementsClient.push()` yields `unchanged` for an actual replay.
- **Identity registry:** `migrations/0111_soorin_external_identity_registry.sql` defines canonical identities, source authorities, provenance observations, aliases and binding conflicts. `utopia-store/src/soorin_identity.rs` supports registration and linking. The initial migration's `FOREIGN KEY (kb_id, utopia_entity_id)` referenced `entities(kb_id,id)` without a unique composite key; a follow-up migration correction now adds the required unique index. **No migration or SQLx-backed test was run here**. Identity registration is **not wired to SOC ingestion/graph resolution**, so storage presence does not guarantee graph identity.
- **Ontology:** importer now compares most Utopia API fields, performs guarded create/link operations, and supports protected token input. Live API behavior, idempotency and materialization remain unverified.
- **Evidence:** Statements adapter creates EvidenceReference nodes with structured evidence field statements. Verify on a persisted typed graph and check multi-evidence relations, retention, and source locator privacy.
- **Models and privacy:** Python embedding provider has bounded in-process LRU and a new outbound policy. The default regex heuristic is **not comprehensive sensitive-entity detection**. `approved_privacy_route=true` / `synthetic_mode=true` are **caller-provided declarations, not cryptographic proof of gateway traversal or synthetic provenance**. The policy must be enforced on a trusted egress boundary, and must include Chat and Reranker clients; current reranker HTTP transport does not invoke it.
- **Retrieval:** Python evaluation still embeds all eligible documents on every dense query; it is not the Rust Utopia pgvector/Tantivy production retrieval. `fallback_enabled=True` in `RetrievalFoundation.search()` ignores provider settings. Native reranker and NER model remain unintegrated.
- **Runtime:** Chat/Embedding are configured by Utopia authenticated Workspace Settings; `SOORIN_*` environment settings only configure Python adapters. A real LLM, embedding model, cross-encoder, Rust CI and isolated Compose build remain unverified.

### Release blockers and ordered follow-up

1. **P0:** Run isolated PostgreSQL migration from scratch and `cargo fmt --check`, `cargo check --workspace`, `cargo test --workspace` with `UTOPIA_TEST_REQUIRE_DB=1`. Validate composite FKs, concurrency, alias upsert and cross-KB constraints. Do not run against the existing SOC Lab.
2. **P0:** Fix end-to-end replay stability and type-safe Statements `external_id` collisions with an explicit migration/backward compatibility plan. Preserve source-observed timestamps while excluding delivery-only metadata from versioned document content.
3. **P0:** Make the SOC identity registry authoritative in the real ingestion/entity-resolution boundary (or explicitly block use until wired), including tenant-to-KB authorization and canonical-ID → Utopia-ID mapping.
4. **P0:** Require verified privacy transformation for **all** external model egress (Chat, Embedding, Rerank), fail closed for unknown/untrusted data, and prohibit caller-controlled bypass from being a production security control.
5. **P0:** Test source-notable/alert/event distinctions, ontology domain/range/inverse apply, Evidence graph retrieval, and temporal `at`/`as_of` over an isolated live Utopia KB.
6. **P1:** Use Utopia native pgvector/Tantivy indexes and bounded candidates; keep Python retrieval labeled offline-only. Integrate optional native reranker and NER only when separate quality/cost benchmarks justify them.
7. **P1:** Update model status reporting and deploy docs with explicit installed/runtime-active/testing columns; do not claim BGE-M3 or a reranker model is deployed.

**Decision:** Not ready to merge or deploy with production SOC data. Preserve `main` and the existing Utopia rc9 lab.
