# Soorin SOC foundation · Current gap analysis

**Decision:** ready for the first isolated local source build with documented
restrictions; not merge-ready and not approved for production SOC data.

This file describes the current branch. Historical findings that were corrected
are retained in Git history and the implementation report rather than repeated
as active defects.

## Closed at source/offline level

| ID | Former risk | Current disposition |
| --- | --- | --- |
| S1-P0-01 | Processing metadata changed source revisions and Statements | v3 source-content checksum and v2 Statements rendering exclude delivery/processing/ledger time; order-independence and exact replay are tested |
| S1-P0-02 | Alert, Notable, Event, Finding, and Rule identities could collapse | Normalizer classifies durable IDs separately and tests Agentic/Splunk variants |
| S1-P0-03 | No durable registry design or cross-KB isolation | Migrations `0111`/`0112` and transactional Rust registry exist; Foundation explicitly keeps them dormant |
| S1-P0-04 | Ontology drift was incompletely compared | Validator covers all 17/15 declarations, inverse reciprocity, names, policies, and enforceable importer fields |
| S1-P0-05 | Evidence metadata/multiple references could be lost | Evidence entities, source metadata, all evidence IDs, tenant/source-scoped evidence identity, and replay tests are present |
| S1-P0-06 | Python settings looked authoritative for Rust | Workspace Settings are documented as the only live Rust Chat/Embedding authority |
| S1-P0-07 | Caller booleans could bypass model privacy | Chat/Embedding/Reranking share the same fail-closed policy; external sensitive content requires deployment-owned verifier attestation |
| S1-P1-01 | Python dense evaluation embedded an unbounded corpus | Filters/candidate limits run before embedding, precomputed vectors are accepted, and the namespaced LRU is bounded |
| S1-P1-02 | NER mappings asserted Organization/System identities | Ambiguous labels are discarded; accepted spans remain generic review-only proposals with source labels |

These are source/offline outcomes, not proof of live PostgreSQL or Utopia graph
behavior.

## Must verify during the isolated build

| Gate | Required evidence |
| --- | --- |
| Rust workspace | `cargo fmt --all -- --check`, `cargo check --workspace`, and workspace tests pass |
| PostgreSQL migrations | Clean PostgreSQL 16/pgvector apply through `0112`; registry FK, concurrency, alias history, conflict, and compare-and-set tests pass |
| Source image | Docker Rust/React image builds from this checkout, starts on `2516`, and passes health checks |
| Ontology | Preview/apply/verify 17 entity and 15 relation types in a disposable KB |
| Replay | Immediate second Statements push returns `unchanged`; status/correction revisions return an observed update action |
| Graph | Background processing completes; expected typed entities, relations, evidence, and graph counts come from the actual API |
| Temporal | `at` and `as_of` results match the synthetic lifecycle fixture |
| Search | Identifier and BM25 queries return indexed synthetic chunks; semantic search runs only when a verified embedding model is configured |
| CPU NER | Reviewed local model files load on CPU; latency, memory, truncation, labels, and synthetic quality are measured |

Use [Pre-build validation](PREBUILD_VALIDATION.md) and [Local E2E
validation](LOCAL_E2E_VALIDATION.md). Missing tools, credentials, models, or jobs
must remain `BLOCKED`, `SKIPPED`, or `NOT RUN`.

## Must fix before merge

- Repair any Rust formatting, compilation, migration, or regression failures
  found by the isolated/CI gates.
- Decide and test the explicit v1-to-v2 Statements external-ID reconciliation
  for any historical source. Never silently migrate existing documents.
- Prove ontology materialization and bitemporal results against actual APIs.
- Run an approved real-provider/model evaluation or keep the provider disabled.
- Review the source-build image, SBOM/dependencies, secret injection, resource
  limits, backup/restore, and operational monitoring.
- Complete security and maintainer review; preserve `main` until these pass.

## Deferred to a later integration sprint

- Activate the persistent identity registry at one authenticated transaction
  boundary: tenant-to-KB resolution, register/observe/conflict, Statements render,
  materialization, and Utopia entity compare-and-set binding.
- Add a versioned Agentic SOC Kafka/Splunk transport and backfill procedure.
- Integrate Privacy Gateway verification with a real deployment-owned attestation
  service; the interface exists, but the Agentic gateway is not connected.
- Add native Rust reranking only after a representative quality/latency/privacy
  benchmark. Python reranking remains evaluation-only.
- Add read-only Auto-Triage/Copilot/Investigator context tools, monitoring, and
  controlled case/report write-back.
- Version Tantivy history if complete historical full-text recall is required.

## Permanent correctness boundaries

- Risk score is a vendor risk signal, never malicious probability.
- Current saved-search text is not historical fire-time evidence.
- Investigation hints are retrieval guidance, not evidence.
- Similarity proposes candidates and never proves identity.
- A policy declaration in ontology YAML is not enforcement unless the adapter,
  Utopia runtime, or acceptance tests implement it.
- No external model receives sensitive production content without verifiable,
  deployment-owned routing approval.
