# Final source hardening and pre-build readiness — 2026-11-15

This report covers the final pass after PR #5. Source readiness requires the
seven automatic CI jobs on the final Git SHA to succeed. It does not certify
the running old image, historical data repair, model quality or deployment.
The [application-only handoff](APP_ONLY_REBUILD_20261115.md) supersedes earlier
startup examples for the existing QA instance.

## A. Git provenance

- Actual starting local SHA: `51cce60a13864c815450882ad2bc2cf09f32785a`;
  initial tree clean. Fast-forwarded to approved merged main
  `fb189015889bbc94b18866548a37330d043daf3c`. PR #5 was not merged again.
- Proved `b141b8ab5602460b4a0a0054091f8f23f28ab33d` reachable from main,
  then deleted personal's `fix/soc-authoritative-materialization-qa`.
  Origin and local had no branch of that name. No unrelated branch removed.
- Actual origin is **GitHub** `SoorinSecurity/Soorin_Bidirectional_Temporal_Knowledge_Graph`,
  not GitLab. Its starting main was the known ancestor `51cce60`; no divergence.
  Upstream Utopia was not integrated or pushed.
- Coherent changes: authority diagnostics, streamed index recovery, bounded
  source-title projection/aliases, strict ten-alert acceptance, CI formatting,
  exact-resolution application-state fix and these operational documents.
- Final SHA and equality must be recorded from `git rev-parse HEAD personal/main
  origin/main` after the last normal pushes/fetches. The session's final delivery
  records that SHA and its exact CI URL; a report cannot embed its own commit SHA.

## B. Findings and changes

| Severity / state | Root cause and affected path | Correction and regression evidence | Remaining risk |
|---|---|---|---|
| High / FIXED | `resolution::resolve_curated_canonical` and receipt diagnostics could depend on canonical-name candidates and label normalization | One shared `inspect_curated_canonical` snapshot checks registry, tenant, active status, unresolved authority conflicts, linked-live target, full candidate count; bounded UUID list reports truncation. Reviewed ontology **keys** select the KB's class. Advisory lock + entity row lock preserve same-key concurrency and human types, including human NULL. Store DB tests cover shared Case, lookalike labels, conflicting linked rows, display renames and human choices. | Historical duplicates deliberately fail closed; generic text extraction retains fuzzy ambiguity. |
| High / FIXED | `soc_ingestion::receipt_entities`, `relation_status` could hide duplicate endpoints behind arbitrary name matches | One diagnostic row per expected key; explicit conflict/count/list metadata; relations use the inspected UUIDs and current source/document-version evidence. Truncated entity/relation arrays are explicit. API DB tests inject a duplicate and reject automatic exact resolution/evidence success. | A historically bound receipt's diagnostics describe the current document, not an immutable historical snapshot. |
| High / FIXED | Persistent curated identity conflict could enter ordinary worker retries | Extraction wraps curated validation/conflict as Terminal; ingestion rejects conflict before waiting for alignment. Existing Deferred handling continues to wait without spending attempts; existing lease fencing and computed-outcome acknowledgement tests remain in the workspace suite. | Old submitted jobs can become terminal on the corrected image; source changes do not reconcile their graph. |
| High / FIXED | Startup index recovery collected the entire DB result, could include deleted-document chunks and trust weak marker presence | `search_recovery` invalidates marker before clearing derived postings, streams live PostgreSQL chunks in batches <=256 rows / ~2 MiB (a single oversized chunk may exceed the byte target), commits batches, fsyncs/atomically renames marker only after success. Startup fails before HTTP/workers on error. Exact marker content plus live count gates reuse. New v3 marker forces one corrected-membership rebuild. DB and injected-stream tests cover deleted/stale entries, empty input, failure after a committed batch, retry, corrupt/missing marker, restart, KB filters and exact chunk citations. | Full recovery is proportional to live source size; count equality does not detect arbitrary external same-cardinality index corruption. Single-app startup is required. |
| Medium / FIXED | Explicit alert titles were discarded; canonical aliases did not reach rendered Statements names | Normalizer retains only explicit `title`/`alert_title`, whitespace-normalized and capped at 512 characters, in `attributes.searchable_metadata` v1. Renderer includes existing entity aliases. No arbitrary raw field or model text becomes identity. Python tests preserve canonical IDs and minimize unrelated raw fields; API DB test traces title through document processing, stored chunk, KB-filtered Tantivy citation and bound graph. | Titles themselves can contain sensitive content: normal admission/privacy rules still apply. Historical chunks are not rewritten. |
| High / FIXED | Submission counts or unrelated search hits could be mistaken for acceptance | New read-only `qa_existing_kb accept` checks complete 1..10 tracked input rows, every receipt bound, exact Alert authority->same graph UUID, shared canonical consistency, expected typed relations and current-version evidence, actual source title in the receipt's document and a chunk citation, Tantivy execution and dense disabled. Native assertions reject duplicates, conflict and truncation. Positive and adversarial mock tests added. | Run this gate before revisions. It is a deterministic lexical gate, not dense/hybrid quality acceptance. |

Canonical event v1 and checksum v3 **algorithms** are unchanged. Adding allowed
title content changes the canonical content checksum when the same historical
raw record is normalized again. Replay original canonical bytes for exact old
receipt replay; do not automatically re-normalize old deliveries under a new
projection. Canonical entity IDs are unchanged. Existing receipt payloads,
documents and authority rows were not rewritten. Alias rendering changes only
newly rendered content; it is not a historical document migration.

No additional SQL migration, applied SQL edit, dependency install, CI-template
change or upstream merge was needed. Normalizer subprocess limits and strict
JSON/schema checks, source authority separation, temporal ordering, reviewed
phrase bindings, fail-closed privacy and read-only MCP contracts remain covered
by the existing isolated tests. NER remains proposal-only.

## C. Pipeline readiness

“VERIFIED” below means source/automated contract evidence. Every live
acceptance gate for the new application image remains **NOT VERIFIED**.

| Component | Source evidence / state | Remaining runtime gate |
|---|---|---|
| Ingestion / Normalization | VERIFIED strict envelopes, nested/encoded input, checksum and source clocks; FIXED bounded title projection | Actual Curated Python subprocess in new image |
| Identity / Authority | FIXED shared resolver and explicit conflicts; real isolated DB regressions | New-KB shared entities under real concurrent workers |
| Document Processing | VERIFIED process-document/chunk/title integration | Restart/persistence on rebuilt image |
| Entity Extraction | FIXED reviewed canonical path; generic ambiguity retained | Worker/model configuration |
| Relation Generation | VERIFIED reviewed relation keys, direction/domain/range | All expected edges for 10 then 240 |
| Type Alignment | FIXED key selection; human decisions preserved | New-KB installed ontology and workers |
| Materialization | VERIFIED bound depends on committed typed facts/evidence | 10/10 then 240/240 |
| Evidence / Provenance | VERIFIED source/current-version checks and recorded-time semantics | Real corrections and citation drill |
| Jobs / Leases / Recovery | VERIFIED Deferred budgets, ownership fencing, acknowledgement recovery contracts | Restart/crash/lease recovery in disposable scope |
| Temporal History / Replay | VERIFIED synthetic revision/replay contracts | 12 revisions, late/equal clocks, `at` / `as_of` |
| Tantivy Lexical Search | FIXED streamed v3 recovery and title-to-chunk integration | Actual old-index conversion and ten-alert recall |
| Dense / Hybrid Retrieval | VERIFIED fingerprint/dimensions, finite vectors, RRF/rerank fallback contracts with mocks | BLOCKED_BY_CONFIGURATION: qualified BGE-M3/reranker artifacts, model endpoints and workspace settings; measure relevance separately |
| GraphRAG / KnowledgeContext | VERIFIED bounded context, temporal/KB filters and citation contracts | Grounded live corpus/context acceptance |
| NER | VERIFIED review-only and artifact/runtime contracts | BLOCKED_BY_CONFIGURATION: qualified Cyber NER cache/endpoint; precision/recall and RAM |
| MCP | VERIFIED read-only scoped authorization/revocation/denied-call tests | BLOCKED_BY_CONFIGURATION: read PAT scoped to new KB, full live calls |
| LLM / Agent | VERIFIED compatible provider/tool/timeout mock contracts | BLOCKED_BY_CONFIGURATION: approved endpoint, model, provider key and tool continuation test |
| Privacy Gateway | VERIFIED fail-closed/no raw fallback and gateway fault contracts | BLOCKED_BY_CONFIGURATION: Gateway URL/key, workspace-tenant map, origin allowlist and synthetic encode/provider/decode drill |
| Docker / Migration / Deployment | VERIFIED static Compose, current UID/Python utility inspection and CI isolated migrations | New image build, backup restore, runtime roles, resource/restart qualification; server deployment unapproved |

## D. Executed checks and limits

| Command / evidence | Result |
|---|---|
| `timeout 60s python3 -m unittest discover -s soorin/tests -p 'test_*.py'` | exit 0; **196** tests. Guard argparse errors and HF retry text are injected tests, not real downloads. |
| `timeout 30s python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v` | exit 0; **7** synthetic tests |
| `timeout 30s python3 -m soorin.e2e.local_validation --report /tmp/soorin-final-offline-e2e.json` | exit 0; **6 PASS, 0 FAIL, 1 BLOCKED, 10 NOT RUN, 1 SKIPPED**. Legacy persistent-registry assertion is blocked by harness capability; no live execution/credentials or embedding inference requested. Overall `passed:true` is offline preflight only. |
| Actual `.env` QA Compose config; example QA+models and production+models `config --quiet` | exit 0; no values/secrets printed, no containers changed |
| Existing app `id`, Python `-S import soorin`, `command -v tar`; existing DB `pg_dump --version` | exit 0; UID/GID 65532, `/app/soorin`, tar present, PostgreSQL 16 pg_dump |
| Read-only QA inventory and shared-Case references | Executed in READ ONLY transactions with timeout; no source rows changed |
| `git diff --check`, `python3 -m compileall -q soorin`, `python3 -m soorin.ops.migrations`, `sh -n docker/install-debian-packages.sh` | exit 0; 105 migrations, no collisions; applied SQL, Cargo.lock and CI templates unchanged from approved baseline |
| `GRAPHIFY_MAX_WORKERS=1 timeout 45s graphify update .` | exit 0; AST only, no model/API request. SQL parser absent, so SQL remains outside the graph; no dependency installed. Generated caches/logs excluded from Git. |

Local cargo/rustfmt are absent; no local Rust compilation or formatter container
was started. Automatic GitHub CI provides fmt, Clippy, workspace build/tests,
frontend, Python and migrations. Its test job supplies disposable pgvector
PostgreSQL, migrates it and sets `UTOPIA_TEST_REQUIRE_DB=1`; DB tests actually run.
Initial runs found formatting and a newly added exact-resolution variable
shadowing error, then exposed a wrong-entity conflict fixture and a shared-test-DB
count race; corrected before the final gate. Index recovery now uses its own
disposable test database (the test role needs CREATEDB). Use the **final** CI run, not
the earlier failed runs or PR #5's success. No workflow was manually dispatched.
CI Clippy uses the existing command without `--locked`; dependencies/lockfile
were unchanged. Future local locked commands remain in the build handoff.

No Docker build/start/recreate, model download/inference, DB migration against
QA, live ingestion, historical repair, provider request or deployment occurred.

## E. Preserved QA and historical reconciliation

Read-only observation: app/DB healthy at 127.0.0.1:2526/2527, project
`soorin-tkg-v1-qa`; Compose labels on both containers identify repository **`.env`**.
Make's `.env.qa` default is for separately initialized QA environments and must
be explicitly overridden here. Preserve both files; never regenerate passwords.
Volumes are `soorin-tkg-v1-qa_soorin_sprint1_data` and
`soorin-tkg-v1-qa_soorin_sprint1_db`. Existing QA uses the DB owner, so it does
not certify production's separate migration/runtime-role permissions or limits.

Preserved KB `Soorin SOC Synthetic Lab`, ID
`01a1de1a-b112-7102-ad27-9eb8923b8a2f`: 10 receipts, 8 bound and 2 submitted;
10 live chunks; 145 live entities, 573 total/live facts (403 typed), 603 evidence
links, 113 typed-source links and 72 canonical identities/authority mappings.
These categories differ from the earlier graph UI edge count. Two stored payloads and two live chunk texts already contain
`Password Spray Detection`; original lexical failure was not simply absence of
that rule name. New source title projection also handles standalone titles.

Affected shared Case canonical key:
`soorin:soccase:05d0ec85b42d05fd67dfe103132a2ccb249f84087636d9a77a6e01cd64b8ed11`.

| Candidate UUID | Authority / type | Initial impacted references |
|---|---|---|
| `01a1de5a-740b-7fa3-a0dc-db0061fba731` | Registry-linked, untyped, extracted type source | 3 facts including history, 3 evidence links |
| `01a1de5a-78f5-7673-8a1b-0bee1f919202` | No registry link, typed `soc_case`, extracted type source | 4 facts including history, 4 evidence links |

The registry-linked UUID is the current authority target, not proof that its
observations dominate the typed candidate. New code reports the conflict and
does not pick or merge either candidate. Other untyped entities/missing evidence
from the old run also require per-key inspection; this pass did not certify all
historical graph rows.

Reconciliation is a separate, backup-first operation:

1. Quiesce writers, capture DB/app/env backups and qualify restore in an isolated
   database. Preserve checksums, image provenance and pre-repair read-only inventory.
2. Export the complete closure for **each** affected key: authority/mapping/
   observation/alias rows, both entities and human decisions, incoming/outgoing
   facts including invalidated rows, `supersedes` chains, `typed_fact_sources`,
   phrase/type bindings, every evidence chunk/document/version and recorded time,
   merge/conflict/audit references and receipts/jobs. Counts above are discovery,
   not a complete losslessness proof.
3. On the clone, establish an explicit reviewed target and reversible UUID/fact
   mapping. Verify type/domain/range, source clocks and original evidence against
   authoritative records. Audit Utopia merge/undo semantics for this closure;
   do not assume a generic merge preserves every temporal/provenance field.
4. Accept a repair only when before/after history queries and evidence checksums
   prove no observation or timestamp lost, no cross-source authority rewritten,
   and undo/restore succeeds. Otherwise retain the conflict and escalate review.
5. Only after separate approval, apply the reviewed transaction/audit operation
   in QA, validate against the snapshot, then retry explicitly selected terminal
   jobs/receipts. Never blanket-requeue, delete candidates or overwrite the
   authority registry. A fresh-KB success does not repair this historical KB.

## F. Decision

After exact-final-SHA CI and normal two-remote synchronization succeed:
**SOURCE_READY_FOR_LOCAL_BUILD**. New-image local E2E and server deployment
remain unverified. See [the bounded app-only rebuild and acceptance commands](APP_ONLY_REBUILD_20261115.md).
