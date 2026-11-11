# Utopia capability matrix for the SOC foundation

> Historical checkpoint. Current behavior and evidence are in [Final acceptance](FINAL_ACCEPTANCE_REPORT.md) and [Production architecture](PRODUCTION_ARCHITECTURE.md).

| Capability | Existing Utopia implementation | Sprint 1 decision |
|---|---|---|
| Source authentication | Source ingest token in `sources_routes.rs`; workspace/KB RBAC in store access | Reuse unchanged |
| Open Statements | Strict e/s/n endpoint, stable external identity, replay/update semantics | Reuse through `StatementsAdapter` |
| Typed graph | Alignment, resolution, materialization, facts ledger | Reuse; evaluate stages separately |
| Entity resolution | Name/vector candidates, adjudication, merges in `resolution.rs` | Extend before entry with deterministic SOC keys; similarity stays review-only |
| Ontology | Runtime entity/relation APIs, domains/ranges, OWL preview/apply | Import Soorin YAML through guarded CRUD adapter |
| World time | `valid_from`, `valid_to`, precision, `at` predicates | Reuse |
| Knowledge time | `recorded_at`, `invalidated_at`, `as_of` predicates | Reuse |
| Chat model | Workspace OpenAI-compatible client and reasoning effort | Reuse; add typed Soorin defaults/readiness profile |
| Embeddings | Workspace OpenAI-compatible client, dimension persistence, pgvector | Reuse; add batch/dimension-tested Soorin adapter for offline foundation |
| Keyword/BM25 | Tantivy current-chunk index | Reuse; document historical recall gap |
| Dense retrieval | pgvector chunk search with model failure fallback | Reuse |
| Hybrid fusion | Deterministic RRF in `utopia-search` | Reuse |
| Cross-encoder reranking | No standalone component in inspected path | New optional Soorin adapter; disabled by default |
| UI | React settings, library, ontology, graph, history, search, jobs | Preserve unchanged |
| Background jobs | Persistent queue and worker retry state | Reuse |
| SOC contracts | None | New versioned standard-library dataclasses + JSON Schema |
| SOC extraction | General open/typed LLM extraction | New deterministic field-aware layer; optional NER only for unstructured text |
| Agentic SOC normalization | None | New read-only contract adapter; no Agentic code changes |
| Evaluation | Utopia unit/integration tests and benchmarks | Add SOC integrity, temporal, and retrieval harnesses |

## Ownership boundary

Utopia remains the only graph database, temporal ledger, authenticated API, and operational UI. The Python package is a contract/adapter/evaluation layer, not a parallel web server. External model adapters cannot write canonical identity and cannot bypass Utopia authorization.
