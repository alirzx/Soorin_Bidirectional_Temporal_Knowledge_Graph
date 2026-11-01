# SOC foundation gap analysis

## Closed in Sprint 1

- Versioned `soorin.soc.knowledge-event.v1` contracts and JSON Schema.
- Explicit retention of vendor extensions, source identifiers, provenance, and curated payload version.
- Tenant/source-scoped deterministic identity with provisional and ambiguous outcomes.
- Field-aware offline extraction for SOC identifiers and observables.
- Real Agentic SOC `llm_payload` and nested OCSF normalization with historical fallback.
- SOC ontology/model card plus previewed, idempotent, non-overwriting API importer.
- Alert lifecycle classification and mapping to Utopia's two axes.
- Strict Utopia Statements adapter and authenticated transport.
- Typed chat/embedding/reranker configuration, redacted public status, fake-provider tests.
- Exact, BM25, dense, RRF, optional reranking, tenant/time filtering, provenance, and status metadata in the reusable SOC layer.
- Offline graph, temporal, and retrieval evaluations with machine-readable output.

## Existing Utopia gaps not expanded into rewrites

1. Tantivy indexes current chunks only. `as_of` BM25 cannot recall content that existed historically but has since been replaced. Sprint 1 documents this rather than redesigning the index.
2. The inspected Utopia retrieval path has no cross-encoder stage or reranker settings persistence. The Soorin adapter is disabled by default and not wired into the rc9 container.
3. Utopia's similarity-driven candidate resolution is general-purpose. SOC authoritative keys must be applied before open graph resolution; no persistent Soorin identity registry migration was required for the offline foundation.
4. Statements document updates preserve record-axis history, but a live isolated-KB experiment was not run because this task preserved the existing installation and no disposable authenticated KB/token was provided.
5. External model privacy routing is deployment-specific. Sprint 1 documents and validates adapters but does not implement the Agentic SOC Privacy Gateway.

## Future integration gaps

- Kafka/Splunk live ingestion, DLQ, backfill, and SOC database synchronization.
- Agentic SOC Auto-Triage/Copilot/Investigator tool registration and runtime reads.
- Production authorization mapping between SOC tenants and Utopia workspaces/KBs.
- Persistent cross-system identity mapping, merge/split review UI, and alias interval storage if later workloads require it.
- Reranker persistence and authenticated UI controls in the Rust runtime after benchmark-driven approval.
- Live embedding dimension/model connectivity validation with approved credentials.

These are explicit future-sprint items, not hidden success claims.
