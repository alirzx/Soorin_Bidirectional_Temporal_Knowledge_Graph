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

## Continuation lifecycle and diagnostics (2026-11-15)

Temporary lease contention and downstream waits use the existing `Deferred`
queue marker: 15-second scheduling, attempt restoration, and a one-hour waiting
window. After that window ordinary finite retry budgets apply. Handler work is
bounded to 90 seconds inside a 120-second owner-fenced source lease; a cancelled
or crashed owner is recoverable after expiry. Queue restart recovery assumes one
application worker process; this patch does not qualify multiple app replicas.

Revisions of one source record serialize in admission order. A pending/submitted
predecessor must complete before its Statements document is replaced. A terminal
predecessor is reported as `soc_revision_predecessor_failed`; repair/retry that
specific predecessor first, then retry the successor. Source observation clocks
must strictly advance against bound revisions. Late/equal changed observations
are quarantined; opaque revision IDs never determine temporal ordering.

`bound` requires a ready/done document, expected typed entities, authority links,
and every supported relation backed by current-document-version evidence.
Already-reviewed phrase bindings still deliver new projection jobs. Human
rejection remains authoritative. Failed document processing may keep waiting
while a real downstream retry is queued/running; exhausted document failure is
reported as `soc_document_failed`, and human rejection as `soc_binding_rejected`.
A failed receipt remains visible and is not silently promoted or mass requeued.

KB administrators may GET `/api/v1/kbs/{kb}/knowledge/receipts/{receipt}`.
It reports source scope, document/version, expected endpoints/types, phrase
status/target/direction, evidence result, failure code and <=30 safe job summaries.
It does not return the canonical payload or `last_error` exception bodies.
The diagnostic evidence view is explicitly **current_document_version**: an old
receipt's historical `bound` status is not a frozen snapshot of a subsequently
updated document. Use historical KnowledgeContext/evidence APIs for history.

Use `POST /api/v1/kbs/{kb}/knowledge/receipts/{receipt}/retry` for a single repaired
receipt. It preserves failed job history, refuses quarantined/bound receipts,
and reuses already queued/running work. Reprocess a failed document via the
existing document endpoint only after its underlying error is corrected.
No broad `/jobs/requeue`, graph rebuild or deletion is part of this procedure.

The new curated HTTP interface is documented in [Manual SOC input](MANUAL_SOC_INGESTION.md).
The producer mapping is [versioned separately](PRODUCER_MAPPING_V1_20261115.md).

## Connector REST contract and acceptance examples

Base path `/api/v1`. Send `Authorization: Bearer <credential>` and `Content-Type: application/json` for JSON bodies. Each `{source}`, `{kb}`, `{receipt}` and graph entity ID in a URL is a UUID. The source-specific push secret, administrator session JWT and KB-scoped reader PAT have different grants. Source rotation requires updating the connector's secret store. Test the replacement token on preview, revoke the old credential, and verify denial. Read PAT revocation is covered by the Rust runtime test. Keep registration closed after bootstrap. The single-source tenant binding presently governs this connector.

| Method and route | Input | Successful response |
| --- | --- | --- |
| POST `/sources/{source}/soc/preview` | Source bearer, exactly `profile` and `record`, bounded to 1 MiB. The binding supplies tenant/system/instance. | `schema_version=soorin.ingestion-preview.v1`, `canonical_event`, `warnings`, `ner_status`, `ner_proposals`, `persistent_writes=false`, `submission_status`, `supports_acceptance_run`. |
| POST `/sources/{source}/soc/ingest` | Same bearer and bytes as preview. | `schema_version=soorin.ingestion-receipt.v1`, UUID `receipt_id`, nullable integer `job_id`, string `status`, boolean `replayed`. Persist the receipt before polling. |
| GET `/kbs/{kb}/knowledge/receipts/{receipt}/status` | KB admin session. No body. | `receipt_id,status,job_id,failure_code,delivery_state,updated_at`. Use for routine polling. |
| GET `/kbs/{kb}/knowledge/receipts/{receipt}` | KB admin session. No body. | `soorin.receipt-diagnostics.v1` with receipt, source/scope, status, delivery state, failure code, current document/version, entities, relations, unsupported count, evidence view, jobs, limits and truncation flags. Before submission the document may be null. |
| POST `/kbs/{kb}/knowledge/receipts/{receipt}/retry` | KB admin session, no request body required. | `receipt_id,job_id`. A failed terminal child, failed terminal parent, bound or quarantined receipt gets 409. |
| POST `/kbs/{kb}/search` | Reader session or scoped read PAT. `q` required, nonblank, up to 4,000 characters. `top_k` optional unsigned integer, default 10, capped at 50. Optional record-time `as_of` is YYYY-MM-DD or RFC3339. Body limit 32 KiB. | `results[]` with `id,document_id,seq,text,filename`, plus `retrieval` as below. |
| POST `/kbs/{kb}/knowledge/resolve` | Reader. Required strings `tenant_id,source_system,source_instance,entity_type,authority_name,source_identifier`, optional string/null `scope`. Unknown fields rejected. | `soorin.identity-resolution.v1` with KB, tenant, status, automatic, candidates and limitations. Accept an unambiguous resolved entity ID only. |
| POST `/kbs/{kb}/knowledge/context` | Reader. Required `tenant_id,entity`, optional `entity_type,at,as_of,limit`. Limit default 40, clamped to 1–100. Historical `as_of` requires a UUID and omits `entity_type`. | `soorin.knowledge-context.v2` with resolved entities, facts, evidence references, time axes, conflict and truncation metadata. Retain citations and partial/unavailable status. |

Preview and ingest share this synthetic request. The contract test normalizes these bytes offline. The examples below use illustrative UUIDs. Values marked as projections list selected response fields.

```json
{"profile":"agentic-soc.splunk-curated.v1","record":{"alert_row_id":"A1","notable_id":"N1","event_time":"2026-10-20T12:00:00Z","source_updated_at":"2026-10-20T12:01:00Z","llm_payload":{"alert_id":"A1","event_time":"2026-10-20T12:00:00Z","alert_time":"2026-10-20T12:01:00Z","rule_name":"Multiple Failed Logons"}}}
```

Preview response projection and subsequent admission, status, diagnostics projection and successful retry examples, respectively. A retry example represents a recoverable dependency after repair.

```json
{"schema_version":"soorin.ingestion-preview.v1","canonical_event":{"source_record_id":"A1","event_type":"security_alert","observed_at":"2026-10-20T12:01:00.000000Z"},"persistent_writes":false}
```
```json
{"schema_version":"soorin.ingestion-receipt.v1","receipt_id":"019a0000-0000-7000-8000-000000000001","job_id":71,"status":"pending","replayed":false}
```
```json
{"receipt_id":"019a0000-0000-7000-8000-000000000001","job_id":71,"status":"submitted","failure_code":null,"delivery_state":"waiting_for_dependency","updated_at":"2026-11-23T10:00:00Z"}
```
```json
{"schema_version":"soorin.receipt-diagnostics.v1","source_scope":{"tenant_id":"tenant-blue","source_system":"splunk","source_instance":"splunk-e2e"},"document":{"document_id":"019a0000-0000-7000-8000-000000000002","status":"ready","graph_status":"done","document_version":1},"evidence_view":"current_document_version"}
```
```json
{"receipt_id":"019a0000-0000-7000-8000-000000000001","job_id":76}
```

Search request and a response projection from controlled degradation. Pre-dedup channel hits, distinct IDs and authorized reloaded chunks can differ.

```json
{"q":"A1","top_k":10,"as_of":"2026-11-23T10:01:00Z"}
```
```json
{"results":[{"id":"019a0000-0000-7000-8000-000000000003","document_id":"019a0000-0000-7000-8000-000000000002","seq":0,"text":"Multiple Failed Logons","filename":"synthetic"}],"retrieval":{"schema_version":"soorin.retrieval-metadata.v1","dense_executed":true,"lexical_method":"postgres_versioned_lexical","lexical":"postgres_versioned_lexical","candidate_count":2,"unique_candidate_count":1,"authorized_candidate_count":1,"reranker_status":"fallback","score_type":"rank_fusion","final_order":"rank_fusion","returned":1}}
```

Resolve then use the returned UUID with context. Curated alert rows use the authority soc_alert_row_id. The legacy canonical Rust fixture uses alert_id for its own A1. The API/DB test exercises historical evidence and cross-KB refusal. Response projections follow each request.

```json
{"tenant_id":"tenant-blue","source_system":"splunk","source_instance":"splunk-e2e","entity_type":"SecurityAlert","authority_name":"soc_alert_row_id","source_identifier":"A1"}
```
```json
{"schema_version":"soorin.identity-resolution.v1","status":"resolved","automatic":true,"candidates":[{"entity_id":"019a0000-0000-7000-8000-000000000004"}]}
```
```json
{"tenant_id":"tenant-blue","entity":"019a0000-0000-7000-8000-000000000004","as_of":"2026-11-23T10:01:00Z","limit":10}
```
```json
{"schema_version":"soorin.knowledge-context.v2","retrieval_status":"partial","knowledge_time":"2026-11-23T10:01:00Z","retrieval_methods":["entity_lookup","temporal_graph","fact_evidence"],"model_versions":{"usage":"none","reason":"deterministic_graph_lookup"}}
```

A successful Search may also return an opaque `request_id` and the additive
`retrieved_candidate_count`, `rerank_candidate_count`, `rerank_batch_count`,
and `fallback_reason` fields. `reranker_status=complete` covers the selected
window. `final_order=cross_encoder_then_rank_fusion` marks a reranked prefix
with unmodified RRF ordering outside it. Keep `fallback` and `disabled` distinct
in client telemetry. Use the configured Search deadline to size client
timeouts. See [Retrieval and reranking](RETRIEVAL_AND_RERANKING.md).

After a lost admission response, resend identical bytes and retain the returned receipt. Use bounded backoff for 429/503 and transport outages. For 409, only the named normalizer capacity or timeout conditions are transport-retry candidates. Poll administratively every 5–30 seconds with an overall deadline. On expiry retain the receipt and resume later. Use diagnostics for child failure classes and versioned evidence. Failed or quarantined dependencies require the documented repair/review process. Consumer code must surface lexical-only results and enabled-reranker fallback. Disabled fallback can return an HTTP error. Production source tokens never need the synthetic harness header.

The executable wire handlers are in `crates/utopia-server/src/api/{soc_curated,soc_ingestion,search_routes,soc_knowledge}.rs`. The full graph context schema is in `soorin/contracts/schemas/knowledge_context_v2.schema.json`. The Server 55 runbook defines release and scale gates.

## Continuous SOC receipt polling

Automatic submission remains opt-in in SOC. A source token authenticates Preview and Ingest. Preserve exact request bytes for uncertain Ingest acknowledgments. A successful admission is a pending receipt. Document processing and graph materialization are required before the receipt becomes bound.

The separate SOC reconciler issues only `GET /api/v1/kbs/{kb}/knowledge/receipts/{receipt}/status`. It checks the receipt and source IDs against the stored binding. Provision a `receipt_status` PAT through `POST /api/v1/me/tokens` using an explicit KB allowlist and a service identity with KB Viewer access. Keep it separate from the source token and the read PAT. Existing KB-admin sessions can use the status route and the separate operator diagnostics. Receipt PATs cannot access the diagnostics list, Search, graph evidence, documents, or MCP.

Enable polling after migration `10009_receipt_status_pat.sql` is applied and both sides agree on the status contract. Poll under a bounded cadence on the private integration network. A recoverable failure remains pending in SOC and the reconciler checks the existing receipt again. Reprocessing and quarantine release remain operator actions using their existing paths.

SOC Case Recon applies a signed workspace and case grant, ranks eligible alert roots across connector bindings, and reads with a scoped reader PAT. Search results remain semantic candidates. SOC accepts a candidate pivot only when a current Context result on a verified source root links its exact document and chunk to one unambiguous graph endpoint.

The receipt PAT uses KB-level authorization. A dedicated SOC KB should have one admitted source authority. If multiple sources share one KB, an otherwise authorized status PAT can see the payload-free status of a known receipt in that KB. SOC separately verifies the returned source UUID against its binding. Create and revoke receipt PATs from the token management UI or the session-authenticated API. See the [canonical production interface](SERVER55_PRODUCTION_RELEASE.md#canonical-hardened-production-interface) for private deployment.
