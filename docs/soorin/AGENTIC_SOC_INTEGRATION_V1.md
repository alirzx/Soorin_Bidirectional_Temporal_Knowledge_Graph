# Agentic_SOC integration v1

Status: source-audited against Agentic_SOC main
`a0a160d1dfbd83304fbb335b8ef8ba871a04cd90`; no live connector deployment.
The earlier `11cd70c` privacy branch and `19a0cee` main are historical checkpoints.
See [current workflow and tool contracts](AGENT_TOOL_CONTRACTS.md) for the updated
API-enriched alert ID semantics and the V1 multi-source ownership limitation.

The source path is Splunk enriched notables → connector envelope/OCSF → raw-events
transport → fusion promotion → durable tenant alert row → fused-alert consumer →
AutoTriage investigation/decision. Fusion `INSERTED`/`DUPLICATE` mean durable;
`UNAVAILABLE`/`FAILED` do not. `alerts.id` / `alert_row_id` is distinct from a Splunk
notable, original event, finding UID, rule, case or investigation-run ID. Preserve
all available source IDs; do not invent missing IDs. The consumer uses the durable
row identity and carries curated `llm_payload`. See [source audit](AGENTIC_SOC_DATA_CONTRACT_ANALYSIS.md).

## Native transport

All paths are below `/api/v1`. Use TLS except local synthetic testing.

| Method/path | Credential / behavior |
|---|---|
| PUT `/kbs/{kb}/knowledge/binding` | KB admin session; binds `{tenant_id,source_system,source_instance}` |
| POST `/sources/{source}/knowledge-events` | Statements source bearer token; dedicated empty source; canonical event v1, checksum `soorin.source-content.sha256.v3` |
| GET `/kbs/{kb}/knowledge/receipts` | KB admin session; counts and newest 100 operational receipts, no event payload |
| POST `/kbs/{kb}/knowledge/receipts/{receipt}/retry` | KB admin; reuses queued/running job, refuses bound/quarantined receipts |
| POST `/kbs/{kb}/knowledge/resolve` | Reader session/PAT plus tenant/source binding; exact current authority lookup |
| POST `/kbs/{kb}/knowledge/context` | Reader authorization plus matching tenant; read-only context v2 |

The binding is deployment-owned. Tenant strings are assertions checked against
that binding; they cannot grant access. Source credentials do not authorize context
reads. Use a separate KB-scoped read PAT for read-only consumers; admin diagnostics still require an admin session.

The general v1 contract retains legacy v1/v2 checksums and reviewed/proposed
objects for historical tooling. Native admission is stricter: checksum v3 only,
1 MiB, 1–128 entities, <=512 relations/facts, <=256 evidence/source references,
known entity types, valid references and timestamps. Only observed/asserted
confidence is admitted; proposed/inferred conclusions and direct retractions need
a separate review workflow. See `soorin/contracts/native_profile.py` and the Rust
validator. Metadata retention follows [Storage policy](SECURITY_BOUNDARIES.md).

Receipt v1 returns `receipt_id`, `job_id`, `status`. HTTP 200 means durably accepted,
not materialized. States are pending → registered → submitted → bound, with
quarantine possible before replacement. Source-clock regression/equality with
changed content and identity conflicts quarantine; no automatic override exists.
Exact source-key/checksum replay reuses the receipt. Retry transport failures,
408, 429 and selected 5xx with bounded backoff and identical canonical bytes.
Do not regenerate observed time or event content on retry. 401/403/404/422 and
schema mismatch require correction/operator review. Failure codes include
`soc_materialization_pending`, `soc_ingest_retryable_failure`, `identity_conflict`
and `late_or_ambiguous_revision_retained_for_review`. Invalid admission returns a
redacted validation error; `soc_sensitive_payload_policy` identifies retention rejection.

## Read-only context

Request `{tenant_id,entity,at?,as_of?,limit?}`; limit 1–100, default 40. `at` is
world time and `as_of` is knowledge time. Historical requests require an entity
UUID and no current-type filter. The response conforms to
`soorin/contracts/schemas/knowledge_context_v2.schema.json` and includes resolved
entities, ledger facts, evidence document/chunk/version references, conflicts,
status, bounds, limitations, and explicit no-model provenance.

`partial` includes missing evidence, conflict or truncation. `bounds.has_more`
is a conservative indication of unexamined candidates/evidence, not a cursor or
exact total. Do not interpret a bounded result as exhaustive. Legacy evidence
without reliable attachment time is unavailable historically. An evidence citation
proves the ledger's provenance, not the truth of an unreviewed security conclusion.
`extractive_answer` validates only exact cited ledger text and preserves partial
status; arbitrary generated prose requires separate evaluation and review.

```python
from soorin.adapters.utopia.knowledge_client import KnowledgeClient
# Obtain tokens from a secret store; never log them.
client = KnowledgeClient(api_origin, source_token=source_token,
                         session_token=reader_token, timeout=10, retries=2)
receipt = client.ingest(source_uuid, canonical_event)
context = client.context(kb_uuid, tenant_id=tenant_id, entity=entity_uuid)
```

The client validates response schema versions, refuses redirects, bounds response
bytes/time/retries, preserves ingestion bytes, and exposes redacted structured
`KnowledgeClientError.code/status/retryable`. It does not acknowledge Kafka on
behalf of Agentic_SOC or poll materialization implicitly. Producers must persist
receipt IDs and acknowledge only according to their own durable delivery policy.

Recon and Forensic agents can retrieve evidence; Responder receives context only
and cannot perform containment through this API; ReportWriter can cite facts;
AutoTriage and Copilot can consume attributed history. Preserve verdicts
`true_positive`, `benign_true_positive`, `false_positive`, `benign`, `needs_review`.
A verdict is an attributed decision, not a verified observation. No automated SOC
write-back is implemented.

Version policy: reject unknown event/context schema versions and preserve stored
checksum versions. Additive response metadata is compatible. Normalizer minimization
changes newly produced content/checksums; rehearse upgrades on a dedicated source
before resuming an older producer. Never mix legacy Statements and native ingestion
on one source or silently rewrite existing IDs/history.

### Small hardening profile corrections

Native relations must match reviewed vocabulary/domain/range and carry declared
source evidence; unknown relations are rejected before persistence. Earlier queued
incompatible events are quarantined as `stored_event_requires_review`, not silently
marked bound. A notable ticket association uses an explicit case/alert; otherwise
it is retained with a review warning without broadening the ontology.
Source update timestamps can advance `observed_at` while original `event_time`
stays stable. The event/checksum version and identity keys are unchanged. Producer
projection corrections can change newly generated content checksums; replay the
same serialized canonical event when retrying an already accepted delivery.

Manual operators can use the [bounded preview/submission workflow](MANUAL_SOC_INGESTION.md).
