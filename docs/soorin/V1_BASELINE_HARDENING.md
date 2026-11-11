# V1 baseline hardening — 2026-11-11

Scope: source/configuration/contracts/static and mock validation before the first
controlled V1 image/runtime qualification. Starting branch
`feature/soc-knowledge-foundation-v1`, SHA
`cf8364a0aa977c713eccec300bb53d72d3285217`. Work branch:
`hardening/tkg-v1-baseline-final`. Final Git/CI evidence is reported separately;
source-ready does not mean production-ready.

## Architecture and confirmed changes

Rust Utopia remains the only authoritative ingestion queue, identity registry,
temporal graph and search backend: PostgreSQL/pgvector, Tantivy and existing
workers. Python performs bounded source projection and optional review proposals;
React presents the established operator flows. No additional graph/vector engine,
microservice or persistent queue was introduced. No migrations changed.

| Confirmed issue / root cause | Implemented correction |
|---|---|
| Current Agentic API enrichment uses alerts.id where old curated input used notable ID | Explicit producer-marker contract branch; conflicting envelope IDs reject; legacy remains compatible |
| Manual helper emitted only NOT RUN and had duplicate HTTP retry code | Structured preview plus explicit submit/status using shared KnowledgeClient |
| Ambiguous JSON / wrong SHA algorithm / nested type context | Duplicate/nonfinite/depth/size guards; field-specific hashes; local nested context; boolean IDs rejected |
| Optional provider timeout/invalid collection could abort deterministic extraction | Bounded review-only proposals with redacted warnings and explicit unsupported script |
| NER serving exposed local cache path as model identity | Response proposals use pinned public model@revision |
| Native Python profile lacked Rust's 1 MiB admission cap | Matching bounded payload preflight; event/checksum algorithms unchanged |
| Registry had no public exact authority resolver | Small authenticated current authority lookup with source/scope/conflict/pending states |
| REST search rejected PATs despite service-consumer use | Shared DocumentReader + membership/PAT KB scope, revocation regression |
| MCP malformed time silently searched current data; execution metadata discarded | Invalid time errors and additive structured retrieval metadata; JSON-RPC envelope validation |
| MCP manual omitted rule tools and described obsolete current-only historical recall | Reconciled 11 read tools, write gate and PostgreSQL historical behavior |
| UI omitted successful reranker state | Explicit completed-reranker label; existing fallback/error/empty states preserved |
| Native acceptance reused legacy equal source clocks for changed revisions | Explicit synthetic update clocks, exact UUID resolution, and late-revision quarantine assertion |
| Harness port assumption could target existing 2516 lab | Explicit alternate loopback approval plus Docker label/volume/port ownership preflight in both harnesses |

## Source trace and preserved invariants

Admission: `api/mod.rs` → `soc_ingestion::ingest` authenticates a Statements source,
validates minimization/checksum/types/signatures/evidence and immutable KB source
binding, then creates receipt/job transactionally. Limits: 1 MiB canonical JSON,
128 entities, 512 relations and 512 facts, 256 evidence/source refs; checksum v3.
Axum's default transport body cap remains an additional upper bound; the native
validator imposes its tighter canonical serialization cap after parsing.

Worker: `process` source lease → `process_locked` → registry registration →
existing Statements/document pipeline → exact SOC alignment → materialize →
registry UUID link and document/typed-relation verification → bound. Unknown
relations fail admission, legacy incompatible queued receipts quarantine, human
rejected/approved bindings remain guarded. Source occurrence, update and delivery
clocks remain separate; opaque revisions never supply ordering. Existing temporal
and registry race regressions are retained. 17 entity/15 relation ontology is
unchanged; importer remains idempotent. No live graph evidence is claimed here.

Read: exact resolution uses existing authority-v1 serialized tuple and source
binding. Context uses authorized entity lookup, bounded temporal facts and eligible
historical evidence. Its current-name discovery remains candidate search; exact
resolution does not use aliases. A historical query requires UUID. Multiple source
namespaces in one native KB remain unsupported; see [agent contracts](AGENT_TOOL_CONTRACTS.md).

Retrieval: independent Tantivy/current or PostgreSQL/historical lexical recall and
fingerprinted dense recall → RRF → KB/time-authorized SQL reload → bounded batches
of reranking → top-k. Unknown/incompatible embeddings excluded. Missing model
falls back; DB failures do not masquerade as lexical success. Rerank indices,
finite scores and full batches are checked before replacing order; failures keep
original ranking only when configured. Existing manual Tantivy reload remains
under writer mutex. Metadata preserves lexical alias and adds lexical_method.

MCP: every HTTP request authenticates a PAT, scope and KB membership; remember
requires write+editor. Eleven read tools, four structured result families; other
outputs remain text. No containment tools. JSON-RPC notifications still return
an empty result, rather than protocol-ideal HTTP 202; streaming/batches unsupported.
This documented existing transport limitation is deferred to a protocol-versioned
change. New tests cover malformed envelope, historical search and channel metadata.

Models: immutable revisions in cpu_models.py; explicit artifact download/manifest
verification separate from offline serving. No weights loaded at module import.
Services are optional profiles, CPU-only, batches <=16, read-only serving caches;
no actual artifacts were inspected or changed during this mission. Mock service
shape tests are not evidence of real model accuracy, latency or memory suitability.

Privacy/security: protected native model transport enforces deployment-owned exact
origins, tenant/workspace mappings, bounded timeouts and no redirects/raw-provider
fallback. Model local endpoints require private deployment boundaries. No real
Gateway requests, credentials inspection or service-token reuse occurred. Gateway
`https://privacy-gateway:8443` is a future independently authorized integration,
not an existing TKG connection. Production config uses separate DB roles, nonroot
app, internal DB/model networks, resource limits, persistent data and exact CORS;
image digests/TLS/secrets/backup verification remain operator gates.

UI source reviewed: Library/upload, KB/ontology, Graph/entity/evidence/history,
Search, model settings/jobs, login and Soorin branding. Existing functions are
preserved; manual SOC workflow is CLI. No browser visual or live API/UI acceptance
was run; partial/missing historical evidence belongs to context responses, not an
invented Search UI history mode.

## Validation record

Local source checks use installed dependencies only. Commands and current outcomes:

| Command | Result |
|---|---|
| `python3 -m compileall -q soorin` | PASS |
| `python3 -m unittest discover -s soorin/tests -p 'test_*.py'` | PASS, 155 tests |
| `python3 -m unittest discover -s soorin/tests/mock_splunk/tests` | PASS, 7 tests |
| `python3 -m soorin.ops.ingest soorin/tests/fixtures/manual_soc_v1.json --raw --tenant-id tenant-blue --source-instance splunk-e2e` | PASS, no HTTP/persistence |
| `node node_modules/vitest/vitest.mjs run` (web) | PASS, 37 files / 270 tests |
| `node node_modules/typescript/bin/tsc --noEmit` (web) | PASS |
| `node scripts/style-guard.mjs` (web) | PASS, 126 files / zero baseline exceptions |
| `cargo fmt --all --check` and `cargo metadata --locked --offline --no-deps --format-version 1` | PASS in cached network-disabled formatting container; host Cargo absent |
| Compose `config --quiet` QA/dev plus model overlay | PASS; no resources created |
| `git diff --check` | PASS |
| Database/API/Rust executable tests | NOT RUN locally; normal remote CI is the execution gate |
| App/frontend/image builds, migrations, startup | NOT RUN locally |
| Real models, live SOC/Gateway, browser UI | NOT RUN |

## V1 capability matrix

| Feature | Implemented | Validation / remaining |
|---|---|---|
| SOC ingestion | Native receipt/job/registry | Mock/source and CI DB gate; isolated runtime pending |
| Manual ingestion | CLI preview/submit/status | Deterministic mock; live submission pending |
| Deterministic extraction | Supported structured fields/IOC patterns | Synthetic tests; arbitrary JSON unsupported |
| NER | Optional review boundary/service | Mock only; English real inference pending |
| Identity resolution | Exact scoped current authority + UUID | Unit/prepared DB tests; real producer mappings pending |
| Graph materialization / ontology | Existing typed 17/15 pipeline | CI DB gate; QA graph/evidence acceptance pending |
| Exact search | Authority resolver / UUID graph | No similarity/name auto-resolution |
| Lexical search | Tantivy current / PostgreSQL history | CI/mock; multilingual runtime relevance pending |
| Semantic / hybrid / reranking | Native pgvector/RRF/optional reranker | Fake providers; real BGE qualification pending |
| Temporal graph | at / as_of ledger | Existing regression/CI gate; runtime lifecycle acceptance pending |
| KnowledgeContext | v2 bounded evidence/conflicts | Deterministic tests; per-fact source-origin projection remains limited |
| MCP | 11 read + gated remember | CI DB gate; external-client protocol qualification pending |
| Frontend | Existing operator UI + retrieval states | Types/tests; browser/device QA pending |
| Docker configuration | Isolated QA env, dev/prod/model templates | Static only; images/ports/TLS/roles pending |
| Agentic_SOC compatibility | Latest-main contract audit and TKG client | No producer registration or live integration; multi-source KB deferred |

## Next-phase qualification checklist (NOT RUN)

Follow [Build and test handoff](BUILD_AND_TEST_HANDOFF.md) only in the next approved
window: inventory unused 2526/2527 and project ownership; isolated image build;
fresh PostgreSQL; fresh and upgrade/replay migrations; API/UI bootstrap; ontology
import; synthetic native admission; receipt-to-bound; node/edge/evidence checks;
exact authority and ambiguous-scope queries; both temporal axes; pinned cache
manifest/permissions; offline embedding; semantic retrieval; reranking; review-only
NER inference; restart/cache reuse; latency/CPU/RAM; auth/revocation/tenant tests;
separately authorized live Privacy Gateway; future Agentic integration. Preserve
all old containers/volumes/caches. No merge into main.

SOURCE HARDENING: pending final Git/CI reconciliation
STATIC AND MOCK VALIDATION: pending final reconciliation
READY FOR ISOLATED LOCAL BUILD: pending final reconciliation
REAL MODEL INFERENCE: NOT RUN
LIVE SOC INTEGRATION: NOT RUN
PRODUCTION READY: NO


## Graphify and CI reconciliation

AST-only refresh after edits: 12,123 nodes, 32,089 edges, 609 communities at the
first code checkpoint. Graphify reports missing tree_sitter_sql for 111 SQL files
and no Cargo.toml nodes; SQL was traced directly. No package installation, semantic
LLM labeling or model use was performed. Graph artifacts remain ignored/untracked.
These metrics describe source code, not a live SOC graph.

Draft PR #2 targets feature, not main. Initial CI run 42984983884 at de855c5 passed
Python/web/migration checks but failed Rust compilation because a new Step label
passed &String instead of &str. Corrected to q.as_str(); no assertion or lint gate
was weakened. New exact-head CI must pass before integration.
