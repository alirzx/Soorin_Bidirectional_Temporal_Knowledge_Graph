# Future Agentic SOC compatibility

Sprint 1 defines contracts only; it does not register tools or modify agent runtimes.

| Future consumer | Useful Sprint 1 output | Required later integration |
|---|---|---|
| Auto-Triage | Exact alert/notable history, prior decisions, evidence references | Tenant-authenticated read adapter and shadow evaluation |
| SOC Copilot | Provenance-preserving hybrid context and temporal filters | ContextBundle provider, citation rendering, privacy route |
| Investigator | Entity neighbors, source events, case history, rule context | Tool registration and bounded investigation queries |
| Recon/Forensic agents | Host/user/IP timelines and evidence references | Approved source retrieval; no raw-log duplication |
| ReportWriter | Versioned decisions, evidence, reports, and cases | Report persistence linkage and citation contract |

Compatibility rules:

1. Canonical TKG UUID/key never replaces SOC alert, notable, event, incident, or case identifiers.
2. Every query is tenant scoped at authorization and storage boundaries, not merely filtered after retrieval.
3. Exact identifiers run before semantic search and bypass reranking.
4. Retrieval scores are ranking signals, not threat probabilities.
5. Model-produced entities/relations remain proposals until validated and cannot override deterministic source identity.
6. Retrieved source text is untrusted data. It cannot register tools, change policies, or provide executable instructions.
7. Agentic SOC remains source of truth for current operational alert/case state until a later synchronization design is reviewed.

The next sprint may implement ingestion and read integration behind feature flags, beginning with replayable synthetic events and shadow reads. It must not infer production write-back authority from this foundation.
