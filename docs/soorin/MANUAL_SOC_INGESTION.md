# Manual SOC input and preview

IMPLEMENTED; deterministic/mock-tested. Live submission and model inference are
NOT RUN in this baseline mission. The CLI reuses the existing Python normalizer
and native Rust receipt queue; it is not a new ingestion server.

## Supported input

A single structured Splunk/curated SOC object must include an explicit source
record identifier (`alert_row_id`, `notable_id`, `source_event_id`, `case_id`,
`investigation_run_id`, `report_id`, or `rule_id`) and a timezone-aware event or
alert timestamp. Tenant/source instance are explicit operator arguments and must
match the server's immutable KB binding. Unknown arbitrary JSON is not interpreted.
Nested `alert`, `raw_alert`, `raw_event`, `ocsf_event`, `raw_data`, `data` envelopes
are supported by the normalizer; do not infer ownership from display labels.
Duplicate JSON keys, non-finite numbers, depth >32 and input >1 MiB are rejected.
Epoch-only timestamps are not accepted by this interface: the producer must
provide an explicit timezone-aware timestamp. Unscoped users/hosts/IPs remain
provisional. A field named `sha256` must contain a SHA-256-length hash.

The current Agentic_SOC API builder marks `_meta.mode=enriched_from_api` and uses
`llm_payload.alert_id` for `alerts.id`. The legacy curated Splunk payload uses it
for a notable. The marker selects the contract; UUID shape never selects it.
An explicit envelope ID conflicting with the marked payload is rejected. Replay
previously accepted canonical bytes; renormalizing old input is not replay.
Finding UID and original event IDs are retained in source metadata. The existing
v1 projection represents finding UIDs as SecurityEvent references; it does not
introduce a new Finding type or claim they are original raw SIEM event IDs.

## Preview without persistence

From the repository root:

```bash
python3 -m soorin.ops.ingest soorin/tests/fixtures/manual_soc_v1.json \
  --raw --tenant-id tenant-blue --source-instance splunk-e2e
```

This prints the canonical event, entities, relations, source evidence and warnings.
It performs no HTTP call or DB write. Output can contain normalized identifiers;
review it locally and do not attach customer previews to public logs. Native
privacy minimization is not semantic DLP. The event keeps checksum v3 and event v1.

The Python `soorin.ops.preview.preview(..., ner=provider)` extension accepts an
explicit provider under caller control. Default is disabled and no model imports
or initialization are triggered. Failures/timeouts/invalid collections become
warnings, deterministic output survives, and at most 128 proposals per text are
accepted. Text is bounded to 4,000 characters. Persian/Arabic script is explicitly
reported unsupported; this English checkpoint does not certify other languages.
Proposals retain model revision/source labels and review_required=true, remain
outside the canonical event, and require the existing human review process. The
CLI intentionally has no switch that implicitly loads a model. Providers must
impose their own execution deadline; an in-process arbitrary provider cannot be
forcibly cancelled by this synchronous adapter.

## Explicit future submission

Only in the separately approved runtime phase, after creating and inspecting the
new QA stack described in [Local development](LOCAL_DEVELOPMENT.md):

```bash
python3 -m soorin.ops.ingest soorin/tests/fixtures/manual_soc_v1.json \
  --raw --tenant-id tenant-blue --source-instance splunk-e2e \
  --base-url http://127.0.0.1:2526 --qa-project soorin-tkg-v1-qa \
  --approved-port 2526 --execute
```

Supply `UTOPIA_SOURCE_ID` and `UTOPIA_INGEST_TOKEN` from the disposable source.
Execution verifies running app/db Compose ownership, exact project-specific
volume names and loopback port mappings through read-only Docker inventory. It
refuses the existing 1516/2516 labs. It does not start Docker or change volumes.
The check cannot protect against an operator concurrently replacing containers;
keep the QA environment exclusively owned during execution.

Receipt and job diagnostics use the separate KB-admin session credential:

```bash
python3 -m soorin.ops.ingest --base-url http://127.0.0.1:2526 --receipts "$UTOPIA_KB_ID"
```

Set `UTOPIA_SESSION_TOKEN` for that read. The existing endpoint returns newest 100
receipts plus counts, job status/attempts and failure codes, without payloads.
Persist the returned receipt ID; replaying the **same canonical event** retrieves
its current receipt. A receipt outside the newest 100 requires exact replay or
operator diagnostics, not an assumed missing job.

HTTP acceptance means durable admission. `pending`, `registered`, `submitted`
are processing stages; only `bound` proves the native materialization checks.
`quarantined` requires review and cannot be retried automatically. Job queued,
running, failed and attempt budgets supplement receipt state; exhausted retries
are not successful graph construction.

## Other ingestion interfaces

| Path below `/api/v1` | Authentication and intended side effects |
|---|---|
| POST `/sources/{id}/knowledge-events` | Dedicated Statements source token; strict canonical SOC admission, receipt/job, registry, typed materialization |
| POST `/kbs/{id}/ingest` | Session editor; ad hoc document text/sections, document processing; no canonical SOC receipt |
| POST `/sources/{id}/ingest` | API source token; stable external document key/upsert/tombstone; no SOC registry contract |
| POST `/sources/{id}/statements` | Statements source token; generic pre-extracted Statements/open knowledge; bypasses native SOC admission |
| POST `/kbs/{id}/documents` | Session editor; multipart document upload and extraction pipeline |

Never mix legacy direct Statements with native receipts on one source. Use Library
for document uploads, Ontology for SOC import, Graph/Entity detail for relationships
and evidence, Jobs/receipt diagnostics for completion, and Search for passages.
Manual SOC preview/submission is currently this CLI, not a new web form.
