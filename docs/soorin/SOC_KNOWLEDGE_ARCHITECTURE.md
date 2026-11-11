# Soorin SOC knowledge architecture

The current implementation is described in [Production architecture](PRODUCTION_ARCHITECTURE.md),
[Security boundaries](SECURITY_BOUNDARIES.md), and [Acceptance evidence](FINAL_ACCEPTANCE_REPORT.md).
Implementation does not imply deployed runtime acceptance.

The complete path is:

```text
Splunk / Agentic_SOC curated record
  -> Python normalization, minimization, canonical event v1 / checksum v3
  -> authenticated Rust native ingestion
  -> durable receipt/job, scoped identity registry, conflict quarantine
  -> Statements document pipeline and open knowledge
  -> exact reviewed SOC type/phrase alignment
  -> typed facts and provenance
  -> PostgreSQL bitemporal graph
  -> authorized hybrid retrieval or KnowledgeContext v2
  -> read-only SOC consumers
```

The ontology contains 17 entity types and 15 relations. `SecurityAlert`,
`SplunkNotable`, `SecurityEvent`, `DetectionRule`, `SOCCase`, `Incident`,
`TriageDecision`, `InvestigationRun` and `EvidenceReference` are distinct concepts.
A correlation edge never makes two source records the same identity. Source
risk scores, analyst assertions and model proposals have separate meanings.
Proposed/inferred conclusions require review before native admission.

Known SOC vocabulary aligns through the existing Utopia binding and materialization
APIs. `observed_on`, `observed on`, and the stored `observedOn` label map to the
same reviewed relation. Unknown terms remain open. Human-approved/rejected
bindings take precedence. Native `bound` now requires typed materialization for
recognized submitted SOC relations as well as identity binding and document
completion; this new gate needs controlled database acceptance.

Corrections retain source document identity while changing checksums. Late or
ambiguous same-source revisions are retained in quarantine instead of overwriting
a newer submitted observation. Source clocks do not replace the server's ledger
clock. See [Temporal model](TEMPORAL_MODEL.md).

Agentic_SOC is an optional producer/consumer. There is no write-back action or
automatic containment in this integration. See [Integration v1](AGENTIC_SOC_INTEGRATION_V1.md).

Native relation validation now rejects unknown keys, invalid domains/ranges and
missing required evidence before persistence; older incompatible queued receipts
are retained in quarantine. No ontology or receipt-state expansion was introduced.
See [current hardening evidence](PREBUILD_HARDENING_REPORT.md).

## V1 baseline update

Current API-enriched Agentic payloads mark `_meta.mode=enriched_from_api`: their `alert_id` is the durable SOC row. Legacy curated Splunk semantics remain supported explicitly. See [manual ingestion](MANUAL_SOC_INGESTION.md) and [V1 ownership constraints](AGENT_TOOL_CONTRACTS.md); ontology and canonical identity/checksum versions remain unchanged.
