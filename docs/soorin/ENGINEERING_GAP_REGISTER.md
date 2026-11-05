# Master implementation register — 2026-11-05

Baseline: `9b18b32`, clean feature branch, 0 behind/64 ahead of main, 110 changed
files. Graphify refreshed: 11,638 nodes / 31,029 edges / 575 communities. SQL
parser unavailable; migrations are inspected directly. Agentic references remain
read-only at `19a0cee` and `11cd70c`.

| ID | Component / severity | Confirmed root cause and affected files | Fix / regression / validation |
| --- | --- | --- | --- |
| M01 | E2E / high | `local_validation.py` accepts open edge wording as typed relations, uses fixture dates as record time, and equates no new failures with completion | Replace evidence criteria, inventory source kind/documents, preserve interruption reports, expose progress and deadlines; fake API regression tests |
| M02 | Alignment / high | Type/phrase handlers require Chat before considering exact declared vocabulary | Deterministic SOC vocabulary through existing binding/materialization APIs; unknown vocabulary remains unresolved/model-dependent |
| M03 | Identity / high | Registry has no caller; normalizer deduplicates IPs before considering field-specific scope | Authenticated recoverable ingestion/registration boundary and scope-aware normalization tests |
| M04 | Retrieval / high | Native RRF has no reranker; TEI Python assumes top_n response size although TEI scores all candidates | Validate all scores, bound and sort; optional native stage with explicit fallback metadata |
| M05 | Models / high | No persistent independent CPU service or download-once command | Optional model services, pinned manifest, explicit initialization, offline startup, fake model contract tests |
| M06 | Egress / critical | Python privacy does not cover native Rust LLM clients | Native fail-closed egress policy and optional gateway transport; mock provider/gateway tests |
| M07 | Embeddings / high | Document vectors have no model fingerprint, so model swaps mix vectors | Model fingerprint, guarded queries and explicit backfill migration/tests |
| M08 | Knowledge / high | Structured query contract is too small and no grounded read-only agent surface exists | Authorized bounded context API/client, temporal/evidence mapping, citation validation |
| M09 | Migrations / high | Local 0111 conflicts with newer upstream 0111 | Never renumber applied migrations; compatibility scanner and explicit reconciliation runbook/tests |
| M10 | DeepSeek / medium | Tool assistant turns discard provider reasoning_content | Preserve protocol field privately across tool rounds; explicit non-thinking mode; contract tests |

## Runtime observations (read-only)

Existing KB `01a1a5c9-7735-7411-b5a5-30022171e7be` has Statements source
`Splunk SOC Synthetic Lab` with 14 documents; `Soorin Sprint1 E2E Scenarios` is
**kind=folder**, 0 documents. Do not convert or overwrite it automatically.
Jobs: 4 align_types failures, 1 align_phrases failure, all explicitly reporting
missing Chat; 16 extraction/process jobs done. Applied migrations 111/112 are
successful. At inventory API memory was 57.88 MiB, DB 45.44 MiB, both idle.
These measurements do not justify pool tuning or explain historic 8–11s stalls.

Native Rust toolchain is absent on host; an existing Rust image is available.
Docker inventory/SQL reads require sandbox approval. SSH github.com:22 timed
out; personal push verification must use an available approved transport.

Implementation commit IDs and final evidence are recorded in
`FINAL_ACCEPTANCE_REPORT.md`; an unavailable live gate is never a pass.
