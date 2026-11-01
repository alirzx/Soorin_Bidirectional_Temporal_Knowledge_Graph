# Sprint 1 architecture audit

## Audited revisions and method

- Soorin TKG: `4bf6a2cb5b98919fe910ba43da7698f7d1b670b9` on the independent Soorin `main` history.
- Agentic SOC `main`: `19a0ceeb5375f2dfb8d50760c883053e50b529e9`.
- Agentic SOC privacy feature: `11cd70c9dcd27a3bf91a364046e3ab86c0cdc201`.
- Graphify: 0.9.51, local `--code-only --cargo` extraction. The baseline pass indexed 725 code files into 9,872 nodes, 28,207 edges, and 411 communities. After the Sprint 1 files were added, the final `graphify update .` refreshed the local graph to 11,432 nodes, 30,535 edges, and 565 communities. `graphify-out/graph.html` is the local aggregated visualization; generated outputs are Git-ignored.

Graphify identified candidate paths, then each finding below was verified in source. SQL symbol extraction was incomplete because optional `tree_sitter_sql` was not installed; migrations were inspected directly with text search. Graphify also returned unrelated same-name symbols for broad queries, so only source-verified relationships are treated as facts.

## Utopia runtime path

```text
Authenticated API route (`crates/utopia-server/src/api/mod.rs`)
  -> source/settings/search/graph/ontology handler
  -> store transaction and/or model client
  -> PostgreSQL temporal ledger + pgvector / Tantivy index
  -> background jobs and React query invalidation
```

### Ingestion and graph materialization

- `crates/utopia-server/src/api/sources_routes.rs` implements the source push and Statements endpoint. The strict envelope is `external_id`, `doc_time`, `deleted`, `e`, `s`, `n`; it enforces 64 KiB, 200 statements, unquoted statement evidence, and declared subjects.
- A Statements document uses source identity `statements:{external_id}`. Same identity and same content is unchanged; changed content is an in-place document revision whose old facts remain on Utopia's record axis.
- `crates/utopia-server/src/extraction_open.rs`, `type_alignment.rs`, `phrase_alignment.rs`, and `crates/utopia-store/src/materialize.rs` move accepted open statements toward aligned typed facts. HTTP `created` therefore proves document ingestion, not typed materialization.
- `crates/utopia-store/src/jobs.rs` and server worker code own asynchronous processing. Tests and reports must keep ingestion, extraction, alignment, resolution, and typed materialization as separate gates.

### Identity and ontology

- `crates/utopia-store/src/resolution.rs` implements open-entity candidate generation, name/vector candidates, adjudication inputs, merge direction, and merge execution. Similarity is useful for candidate discovery but is not a safe SOC identity key.
- `crates/utopia-store/src/names.rs` stores current and historical names on the record axis.
- `crates/utopia-store/src/ontology.rs` owns entity/relation types, domains, ranges, datatypes, qualifiers, inverse/sub-property links, and constraints.
- `crates/utopia-server/src/api/ontology_routes.rs` provides authenticated viewer/editor APIs, including create/update/delete and OWL import preview/apply. Preview and apply share the same OWL plan. Sprint 1's SOC YAML importer uses CRUD APIs because native import accepts RDF/OWL, not the Soorin policy format.

### Temporal model

- `migrations/0003_graph.sql` establishes append-oriented facts with `valid_from/valid_to` (world axis) and `recorded_at/invalidated_at` (knowledge axis).
- `crates/utopia-store/src/world_axis.rs` and `record_axis.rs` centralize query predicates.
- `crates/utopia-store/src/graph.rs` exposes current views, entity history, and change events. `crates/utopia-server/src/api/tools_graph.rs` exposes timeline and fact tools.
- Utopia owns invalidation when a document revision replaces prior statements. The Soorin adapter maps event time into statement `when` and does not fabricate `invalidated_at`.

### Models and retrieval

- `crates/utopia-core/src/models.rs::LlmSettings`, `crates/utopia-store/src/settings.rs`, and authenticated `settings_routes.rs` persist workspace chat/embedding settings. API responses expose only `has_*_key`, never key values.
- `crates/utopia-server/src/llm_util.rs` constructs OpenAI-compatible `utopia_llm::LlmClient` instances and model concurrency gates. `crates/utopia-llm/src/lib.rs` implements chat, tools, streaming, embeddings, timeout/error handling, reasoning effort, and response validation.
- `crates/utopia-server/src/retrieval.rs` runs Tantivy BM25 and pgvector retrieval concurrently, fuses stable channel lists with reciprocal rank fusion, then reloads temporally eligible chunks.
- Embedding absence/network failure degrades to BM25. Vector database errors remain observable.
- Historical limitation: vector and chunk reload honor `as_of`, but Tantivy contains only current chunks. Historical BM25 cannot recall text replaced since the requested knowledge time; it filters false current hits but has incomplete historical recall.

### Security, jobs, and UI

- Route handlers use `AuthUser` plus workspace/KB role checks in `utopia-store/src/access.rs`. New ontology writes require editor; settings require workspace admin; graph/search reads require viewer.
- Background job persistence and retry state live in `utopia-store/src/jobs.rs`.
- The React UI remains authoritative. `web/src/pages/Settings.tsx`, `Graph.tsx`, `EntityHistory.tsx`, `Ontology.tsx`, and `Library.tsx` already cover model settings, graph/temporal inspection, ontology, sources/documents, and job state.
- No UI replacement or unauthenticated configuration endpoint is introduced in Sprint 1.

## Reuse versus extension decision

- Reuse Utopia: graph storage, bitemporal ledger, Statements ingestion, ontology CRUD/import, chat/embedding clients, BM25, pgvector, RRF, authentication, jobs, and React UI.
- Soorin-specific modules: versioned SOC contracts, domain ontology/policy, authoritative identity keys, field-aware extraction, Agentic SOC normalization, Statements rendering, controlled semantic text, provider-neutral reranking, and offline evaluation.
- Deferred targeted runtime integration: wiring the Soorin reranker after Utopia RRF and exposing its settings in the existing authenticated Settings UI. Sprint 1 supplies the tested adapter and configuration without changing the current rc9 runtime or its data.

## Graphify queries used

- `How are open statements ingested and resolved?`
- `How does workspace model configuration reach the embedding client?`
- `How does hybrid retrieval combine BM25 and vector results?`
- `Which modules implement temporal graph queries?`
- `Where are entity identity and merge decisions implemented?`

The strongest extracted paths were Statements → source handler, settings → embedding client, and retrieval → vector/BM25/RRF. Temporal and identity queries contained same-name false neighbors; the conclusions above come from direct source inspection, not those inferred neighbors.
