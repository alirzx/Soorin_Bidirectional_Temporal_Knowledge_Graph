# Sprint 1 and final pre-build implementation report

## Scope and history

The work remains on `feature/soc-knowledge-foundation-v1`. The verified start
of the final hardening pass was `9ec66ef7c13fc743752f3d81276a11b36931fd6e`,
which already contained the 30 Sprint 1 and follow-up commits after Soorin
`main` baseline `4bf6a2cb5b98919fe910ba43da7698f7d1b670b9`.
Those commits were inspected and retained; none was amended or rewritten.

The final pre-build series through `18e2ac5` contains 14 commits after
`9ec66ef`, separated by responsibility:

| Commit | Outcome |
| --- | --- |
| `a261bb0` | Source-content v3, replay/order stability, schema and legacy identity compatibility |
| `367a156` | Registry composite boundaries, append-oriented aliases, ambiguity and concurrency tests |
| `b1b7cae` | Pinned CPU NER, safe label mapping and deterministic-first review proposals |
| `b51330f` | One fail-closed outbound policy across Chat, Embedding and Reranking |
| `e656a1d` | Bounded evaluation candidates/vector cache and configured reranker fallback |
| `cf6c0f4` | Exact ontology validation and semantic evidence anchors |
| `3e5383e` | Multi-evidence and temporal revision coverage |
| `337577c` | Workspace Settings authority and embedding migration warning |
| `c8ef855` | Actual Agentic contract findings and dormant-registry boundary |
| `ad3d340` | Docker source-copy fix, isolated Compose and feature-branch CI gates |
| `cc87c8a` | Synthetic, lab-safe E2E fixture/harness and machine report |
| `b0a4a8e` | Product README, current gap register and five architecture diagrams |
| `34f8b68` | Current validation evidence, Graphify audit and release gates |
| `18e2ac5` | Conflict-row tenant/entity-type constraints found in final manual registry review |

The final graph-count synchronization commit that contains this wording is
documentation-only; `git log` is authoritative for its resulting hash.

Agentic SOC was used read-only at:

- `main`: `19a0ceeb5375f2dfb8d50760c883053e50b529e9`
- `feature/remote-privacy-gateway-integration`:
  `11cd70c9dcd27a3bf91a364046e3ab86c0cdc201`

No Agentic files, existing Utopia/SOC Lab KB, database, image, data directory, or
volume was modified. The organization and upstream remotes were not pushed.

## Architecture evidence

Graphify 0.9.51 was refreshed after the source changes. The local code graph now
contains **11,637 nodes, 31,028 edges, and 575 communities**. Generated
`graphify-out/` files remain ignored and local. The refresh reported that
`tree_sitter_sql` is absent, so all SQL migrations were also inspected directly;
Graphify was navigation evidence, not the authority for SQL or runtime claims.

Source inspection confirmed two separate active paths:

```text
Statements source -> source handler -> open extraction/alignment
  -> Utopia resolution/materialization -> bitemporal graph

Workspace Settings -> Rust Chat/Embedding clients
  -> Tantivy + pgvector channels -> RRF -> knowledge context
```

Soorin Python code remains an external library/CLI/evaluation boundary. It is
not packaged as a long-running service and does not silently replace either
Utopia path.

## Implemented foundation

### Contracts, replay, evidence, and time

- `soorin.soc.knowledge-event.v1` defines `SecurityKnowledgeEvent`,
  `CanonicalEntity`, `KnowledgeRelation`, `TemporalFact`, `EvidenceReference`,
  `AlertRevision`, `KnowledgeQuery`, and `KnowledgeContext`.
- Source-content checksum v3 canonicalizes set-like collections and ignores
  delivery/processing/ledger-only time. v1 and v2 algorithms remain byte- and
  order-compatible with their historical behavior.
- Dataclass validation and the published JSON Schema agree on required fields,
  confidence vocabulary, optional enrichments, references, duplicate IDs,
  timestamps, and bounded JSON serialization.
- Statements v2 sorts entities/relations/facts/evidence, separates entity kind
  in external identity, preserves all evidence IDs in canonical qualifiers, and
  retains v1's exact historical pipe-hash option.
- Evidence node identity includes tenant, source system, source instance, and
  evidence ID. Semantic source records anchor evidence instead of whichever
  entity ID sorts first.
- Lifecycle code and cases distinguish replay, occurrence, correction, state
  change, supersession, retraction, and late arrival while preserving world
  time (`at`) and knowledge time (`as_of`).

Historical v1 documents are not automatically migrated to v2. An operator must
inventory an existing source, choose keep-v1 or create a reconciled v2 source,
compare identities/revisions, and only then cut over.

### Identity registry

Migrations `0111` and `0112` define canonical identities, authorities,
observations, alias history, conflicts, and optional Utopia entity binding.
Composite foreign keys keep authority/alias/conflict rows in the same KB,
tenant, and entity type as their canonical identity. Alias provenance is
append-oriented with exact-replay occurrence counting; conflicting candidates
become ambiguous; Utopia binding is a same-KB compare-and-set.

Foundation deliberately selects **Option B**: no active normalizer, Statements,
or materialization caller invokes the registry. Tables and Rust functions are
not evidence of runtime activation. Sprint 2 must integrate tenant-to-KB auth,
registration, observation/conflict, Statements render, and entity binding at one
tested transaction boundary.

### Agentic SOC compatibility

The verified connector Notable precedence is `source_guid`, then
`source_event_id`, then `event_id`, then `orig_sid@@orig_rid`; the curated
`llm_payload.alert_id` represents the notable. Fusion `finding.uid` carries
source-event identity while the rule ID remains separate. Worker envelopes have
a durable alert-row fallback.

Risk score is not treated as malicious probability, investigation hints are not
evidence, and current rule configuration is not asserted as historical fire-time
configuration. Missing `llm_payload` and historical OCSF forms have explicit
fallback paths. No live Agentic connector or Kafka integration was added.

### Extraction and optional CPU NER

Structured deterministic fields are authoritative. Only explicitly unstructured
fields may reach optional NER. The adapter pins
`bnsapa/cybersecurity-ner` to immutable revision
`1ad52f1a7686a58da2a427c0706d8b868df47181`, uses CPU device `-1`, local files,
safe tensors, bounded input, no remote code, and lazy initialization.

The published `Indicator`, `Malware`, and `Vulnerability` labels become generic,
review-required Indicator proposals with their original label retained.
`Organization` and `System` are discarded because neither proves a Host or other
authoritative SOC identity. Unsupported scripts, missing dependencies, malformed
output, duplicates, and provider failure have tested safe behavior. Real model
weights and CPU inference remain unexecuted.

### Ontology and graph structure

The ontology declares exactly **17 entity types and 15 relation types**. The
validator checks counts, names, domain/range, cardinality, confidence,
provenance, attributes, and reciprocal inverse definitions. The guarded importer
compares every field it projects and refuses conflicting overwrite.

The Statements vocabulary matches the ontology, including `OBSERVED_ON`,
`ORIGINATED_FROM`, `INVOLVES_USER`, `DETECTED_BY`, `CORRELATED_WITH`,
`MAPPED_TO_TECHNIQUE`, `SUPPORTED_BY`, `PART_OF_CASE`, and
`TRACKED_BY_TICKET`. Domain/range and supported axioms participate in Utopia
consistency/reasoning; policy-only provenance/confidence/attribute declarations
are not misrepresented as universal SQL gates.

### Models, privacy, and retrieval

Authenticated Utopia Workspace Settings remain authoritative for live Rust Chat
and Embedding. Python `SOORIN_*` profiles are SDK/development/evaluation only.
The candidate `BAAI/bge-m3` 1024-dimensional profile is not deployed.

Chat health, Embedding, and HTTP Reranking use the same outbound policy. Endpoint
trust is deployment-owned (`local_trusted` or `external`); synthetic traffic
requires deployment test mode; sensitive external content requires an injected
verifier returning an attestation ID. `block_all` has precedence and no caller
boolean grants access. Errors omit provider bodies and payloads.

The production search engine remains Rust Tantivy + pgvector + RRF. Python
retrieval is explicitly evaluation-only: tenant/type/time filters run before
candidate construction, exact identifiers are type-aware, dense work is bounded,
precomputed vectors are accepted, and computed document vectors use a bounded
namespaced LRU. Reranker fallback follows provider configuration.

Changing a workspace embedding model/dimension is not a proven complete document
reindex because `chunks.embedding` has no model-identity column.

### Docker, CI, and local acceptance

- The Docker builder now copies `web/src/palette.ts`, required by Rust
  `include_str!`; runtime health checks have `curl` available.
- Isolated Compose binds API/UI `2516` and PostgreSQL `2517` to loopback, uses
  independent `soorin-sprint1` volumes, and does not keep public registration
  open after bootstrap.
- CI covers this feature branch and includes Python compilation, full foundation
  tests, fixture evaluation, and whitespace checks without model downloads.
- The E2E CLI defaults to offline mode, rejects the existing `1516` lab, accepts
  only loopback `2516`, separates source/session credentials, pushes only the
  isolated tenant, redacts errors, and emits machine-readable status values.

## Observed validation on 2026-11-02

| Gate | Observed result |
| --- | --- |
| Python compilation | `python3 -m compileall -q soorin` passed |
| Foundation tests | **106/106 passed** |
| Mock-Splunk tests | **7/7 passed** |
| Mock fixture | **9 synthetic records, 122 open Statements** |
| Graph-integrity fixture | Passed: 10 events, 54 entities, 28 relations, 171 rendered statements |
| Temporal evaluation | **7/7 gold cases passed** |
| Retrieval regression | BM25, hybrid, and deterministic-reranked modes each Recall@3/MRR/nDCG@3 1.0; failure rate 0 on the 4-document synthetic comparator |
| E2E offline preflight | 6 PASS, 0 FAIL, 1 BLOCKED, 1 SKIPPED, 10 NOT RUN; live operations were not requested |
| Frontend tests | **36 files, 268 tests passed** |
| TypeScript | `tsc --noEmit` passed |
| Frontend production build | Passed; style guard 125 files; Vite warned that the 1.82 MB JS chunk exceeds 500 kB |
| Compose syntax | Isolated and source-build overlay configurations both passed |
| Graphify refresh | 11,637 nodes, 31,028 edges, 575 communities |

The retrieval scores are synthetic regression results, not model-quality or
production-relevance claims.

## Pending validation

- `cargo`, `rustfmt`, and `psql` were unavailable on this host. Rust formatting,
  compile/workspace tests, clean PostgreSQL migration through `0112`, idempotent
  migration, and registry SQLx tests are **NOT RUN**.
- The lengthy Docker source image build was intentionally not launched during
  static polish. Source build/start/health are **NOT RUN**.
- No live disposable KB credentials were provided. Statements `unchanged`,
  ontology apply, jobs, typed graph assertions, `at`/`as_of`, and live search are
  **NOT RUN**.
- No model weights or approved provider credentials were present. Actual CPU NER,
  Chat, Embedding, and cross-encoder calls are **NOT RUN**; semantic E2E is
  **SKIPPED**.
- Mermaid source uses standard GitHub syntax and the banner WebP exists. A local
  Mermaid renderer was not installed, so renderer-level visual QA is **NOT RUN**.

## Readiness

**READY WITH DOCUMENTED RESTRICTIONS** for the first isolated local source build
and E2E phase. The conclusion is supported by clean source/offline/frontend/
Compose gates and an explicit safe harness. It is not `MERGE READY`: Rust,
PostgreSQL, live graph history, source-image, and real-model gates remain.
