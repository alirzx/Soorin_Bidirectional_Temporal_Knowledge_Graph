# Sprint 1 implementation report

## Scope and repository state

Sprint 1 was developed on `feature/soc-knowledge-foundation-v1` from the verified Soorin baseline `4bf6a2cb5b98919fe910ba43da7698f7d1b670b9`. The Agentic SOC checkouts were inspected read-only at `main` `19a0ceeb5375f2dfb8d50760c883053e50b529e9` and `feature/remote-privacy-gateway-integration` `11cd70c9dcd27a3bf91a364046e3ab86c0cdc201`. No Agentic SOC files were changed.

The existing `Soorin SOC Lab` knowledge base, rc9 image, database, data directory, and Docker volumes were not written, reset, rebuilt, or removed. The Sprint 1 Compose file uses project name `soorin-sprint1`, ports 2516/2517, and independent named volumes. No new local service was started during validation.

## Architecture and Graphify analysis

Graphify 0.9.51 was installed as an isolated tool and registered for Codex. A local code-only/Cargo extraction was queried for Statements ingestion, model-setting flow, hybrid retrieval, temporal queries, and identity resolution. Source inspection confirmed the results and rejected broad-query false neighbors. The final refreshed local graph contains 11,432 nodes, 30,535 edges, and 565 communities. Its generated files are intentionally ignored by Git:

```text
graphify-out/graph.json
graphify-out/graph.html
graphify-out/GRAPH_REPORT.md
```

Graphify's inferred edges were used only for navigation. Optional SQL parsing was unavailable because `tree_sitter_sql` was not installed, so migrations were inspected directly.

The architecture audit concluded that Utopia remains authoritative for authenticated APIs, storage, bitemporal graph state, ontology persistence, model clients, BM25/pgvector/RRF retrieval, jobs, and UI. Soorin owns versioned SOC contracts and policies, normalization, deterministic identity/extraction, Statements rendering, model-adapter validation, optional reranking adapters, and offline evaluation.

## Implemented foundation

### Contracts and provenance

- `soorin/contracts/knowledge_event_v1.py` implements `soorin.soc.knowledge-event.v1` with `SecurityKnowledgeEvent`, `CanonicalEntity`, `KnowledgeRelation`, `TemporalFact`, `EvidenceReference`, `AlertRevision`, `KnowledgeQuery`, and `KnowledgeContext`.
- Deterministic canonical JSON/checksums, UTC timestamp normalization, version enforcement, reference integrity, duplicate-source detection, deliberate vendor-field retention, and a 1 MiB event limit are enforced.
- `soorin/contracts/schemas/knowledge_event_v1.schema.json` supplies a machine-readable interchange schema.

### Ontology, identity, extraction, and temporal behavior

- `soorin/ontology/soc_ontology_v1.yaml` defines 17 entity types and 15 relation types with domain/range, temporal, cardinality, provenance, inverse, and confidence policies.
- `soorin/ontology/importer.py` validates and previews changes, requires an explicitly selected authenticated KB for apply, creates missing types only, refuses conflicting overwrite, and verifies the result.
- `soorin/identity/` implements tenant/source/scope-aware canonical keys, hostname/IP/principal normalization, aliases, provisional identities, ambiguity, and merge candidates. Similarity is never an authoritative merge key.
- `soorin/extraction/` implements typed field-aware offline extraction. Regex enrichment is restricted to genuinely unstructured fields and excludes SPL, macros, and investigation hints as evidence sources. NER enrichment is optional and contract-validated.
- `soorin/temporal/lifecycle.py` distinguishes exact replay, new occurrence, correction, state change, supersession, retraction, and late arrival and maps domain time to Utopia's world/record axes without inventing ledger timestamps.

### SOC and Utopia adapters

- `soorin/adapters/splunk/llm_payload_normalizer.py` accepts mappings or JSON strings, unwraps historical OCSF forms, normalizes actual Agentic SOC field families, retains dynamic vendor fields, and separates observed data, analyst assertions, inferred/model content, rule configuration, and retrieval hints.
- `soorin/adapters/utopia/statements_adapter.py` renders stable `external_id` plus strict `e`/`s`/`n` Statements documents, enforces 64 KiB and 200-statement limits, and validates authenticated API responses and transport failures.
- All added fixtures are labeled synthetic and use reserved example namespaces.

### Models, retrieval, and evaluation

- `soorin/models/configuration.py` provides typed Chat, Embedding, and Reranker settings with environment defaults followed by authorized workspace overrides. Public views expose only `has_api_key`.
- `soorin/models/openai_compatible.py` supplies a narrow Chat readiness probe, an OpenAI-compatible embedding client with batching, response-order and dimension validation, retry/backoff, caching, normalization, and a deterministic fake.
- `soorin/retrieval/reranker.py` supports Cohere v2, Jina v1, and TEI response contracts, stable candidate IDs, bounded text, validation, deterministic ties, and RRF fallback.
- `soorin/retrieval/foundation.py` is an offline, reusable compatibility/evaluation layer for exact lookup, BM25, dense retrieval, RRF, optional reranking, tenant/time filtering, deduplication, provenance, and `complete`/`partial`/`fallback`/`unavailable` status. It does not replace Utopia's Rust retrieval runtime.
- `soorin/evaluation/` emits JSON for graph-integrity, temporal, and retrieval checks. The tiny synthetic benchmark is a regression fixture, not a production quality claim.

The executable example settings are in `soorin/config/soorin.example.env`; the auditable domain profile is in `soorin/model_cards/soc_knowledge_model_card_v1.yaml`. No credentials, provider URLs, or production model claims are committed.

## Runtime changes

- Rust: no source changes and no database migration. Existing Utopia storage/API behavior is reused.
- HTTP API: no new route or unauthenticated endpoint.
- UI: no source changes; the original React UI and authenticated Settings flow remain authoritative.
- Docker: `docker-compose.soorin-dev.yml` adds an isolated source-build path only.
- Git ignores: local Graphify output and local Sprint 1 data directories are excluded.

Reranking is deliberately disabled by default and is not wired into the rc9 server. Wiring it after Utopia RRF, adding authenticated persistence/UI, and approving it with a representative benchmark are later integration tasks.

## Validation evidence

Commands executed on 2026-11-01:

```text
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
  61 passed

python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
  7 passed

python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
  9 synthetic records, 122 open statements

python3 -m compileall -q soorin
  passed

python3 -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
  passed; 10 events, 62 entities, 37 relations, 97 rendered statements

python3 -m soorin.evaluation.temporal_cases
  7/7 passed

python3 -m soorin.evaluation.retrieval_benchmark
  BM25, hybrid, and hybrid+deterministic-reranker each produced
  Recall@K=1.0, MRR=1.0, nDCG@K=1.0, failure_rate=0.0 on the tiny fixture

docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml config --quiet
  passed

cd web && corepack pnpm test
  36 files, 268 tests passed

cd web && corepack pnpm typecheck
  passed

cd web && corepack pnpm build
  passed; Vite reported the existing >500 kB chunk advisory
```

No live Chat, embedding, or reranker health test was run: no approved endpoint/credential set was present. Fake-provider response, timeout, malformed-output, dimension, and fallback tests passed. Therefore no live embedding dimension or provider readiness is claimed.

Rust checks were attempted but not completed. This host has no `cargo`; a disposable `rust:1-slim-bookworm` image pull was stopped after the registry made no progress for several minutes. `cargo fmt --all -- --check`, `cargo check --workspace`, and `cargo test --workspace` remain infrastructure-blocked. No Rust source changed in this sprint, but that does not turn the unexecuted checks into passes.

A live isolated-KB Statements lifecycle experiment was also not run because no disposable authenticated KB/source token was supplied. Contract rendering, replay identity, response handling, temporal classification, and importer behavior were verified with offline transports. An HTTP `created` result, when later tested, must still be reported separately from extraction, alignment, resolution, and typed materialization.

## Known limitations and next-sprint boundary

1. Utopia Tantivy contains current chunks; historical `as_of` BM25 can filter current false hits but cannot recall replaced historical text.
2. The Python SOC retrieval layer is a tested compatibility/evaluation boundary, not a second production API. Native reranker integration remains deferred.
3. Persistent cross-system identity mappings and merge/split review state may require a minimal Soorin-owned migration after real ingestion requirements are known.
4. Live ontology apply/verify, provider health/dimension checks, and full Statements temporal experiments require explicitly isolated credentials and resources.
5. Rust workspace regression gates must run in CI or on a host with the repository toolchain.
6. Agentic SOC consumers, Kafka/Splunk polling, database backfill, privacy-gateway routing, agent tools, case synchronization, and production write-back remain out of scope.

Subject to the explicitly blocked live and Rust gates above, the contracts, policies, adapters, offline model/retrieval components, synthetic fixtures, and engineering documentation are ready to serve as the input boundary for a future isolated SOC ingestion/integration sprint. They are not a claim that live SOC integration or production deployment is complete.
