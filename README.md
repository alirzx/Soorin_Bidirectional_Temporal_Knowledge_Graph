<div align="center">

![Soorin Temporal Knowledge Graph banner](assets/banner.webp)

# Soorin Temporal Knowledge Graph

**Temporal security intelligence · Provenance-aware knowledge · Hybrid graph retrieval**

An independent knowledge service for security entities, evidence, relationships,
and historical state, built on Utopia and designed for future Agentic SOC use.

[Architecture](docs/soorin/SOC_KNOWLEDGE_ARCHITECTURE.md) · [Local development](docs/soorin/LOCAL_DEVELOPMENT.md) · [E2E validation](docs/soorin/LOCAL_E2E_VALIDATION.md) · [Engineering docs](docs/soorin/README.md)

</div>

> [!IMPORTANT]
> **Release-candidate foundation; not production or merge ready.** The SOC Python
> boundary is offline-tested and the original frontend build is validated. Rust,
> PostgreSQL migrations, source-image build, live graph history, and real model
> inference remain explicit gates for the isolated build phase.

## What Soorin TKG does

Soorin TKG turns source-observed security records into replay-stable,
tenant-scoped knowledge events with explicit evidence and two time axes. Utopia
then provides authenticated Statements ingestion, ontology alignment, entity
resolution, bitemporal graph persistence, Tantivy/pgvector retrieval, jobs, and
the React operator UI.

The current branch implements:

- `soorin.soc.knowledge-event.v1`, representative JSON Schema validation, stable
  v3 source-content checksums, and exact legacy v1/v2 compatibility paths.
- Agentic SOC/Splunk normalization that keeps durable SOC Alert, Splunk Notable,
  source Event/Finding, Detection Rule, Case, and Ticket identities separate.
- Deterministic structured extraction and conservative tenant/source/network
  canonical keys; optional CPU NER emits review-only proposals.
- EvidenceReference projection, multi-evidence qualifiers, source revisions,
  and world-time/knowledge-time lifecycle classification.
- A 17-entity/15-relation SOC ontology with guarded, create-only import.
- A dormant PostgreSQL identity registry with cross-KB constraints,
  append-oriented alias evidence, conflict state, and compare-and-set Utopia
  binding. It is **implemented but not active in ingestion**.
- One fail-closed Python outbound policy for Chat, Embedding, and Reranking, plus
  bounded offline exact/BM25/dense/RRF/reranking evaluation.
- Isolated Docker/CI preflight and a synthetic E2E harness that refuses the
  existing lab.

## Status by execution boundary

| Capability | Implemented | Offline-tested | Runtime-active |
| --- | --- | --- | --- |
| Utopia API, UI, jobs, graph ledger, ontology, Tantivy, pgvector, RRF | Yes | Existing Rust/frontend tests | Yes in a built Utopia service |
| SOC contract, normalizer, extraction, identity keys, Statements render | Yes | Yes, synthetic only | External CLI/library; not a server sidecar |
| SOC ontology declaration/importer | Yes | Validator and fake API | Live isolated import pending |
| Persistent Soorin identity registry | Yes | Source/SQL tests prepared | No; deliberately dormant |
| CPU cybersecurity NER | Adapter and pinned revision | Mock/provider tests | Disabled; real CPU inference pending |
| Python reranker | Provider adapters | Fake transport/fallback tests | No native Rust integration |
| Agentic SOC connector | Contract compatibility documented | Read-only source audit | Not implemented |

## Data lifecycle

```text
future Agentic SOC / synthetic fixture
  -> llm_payload normalization
  -> deterministic extraction (+ optional review-only NER)
  -> canonical identity + evidence + temporal contract
  -> replay-stable Utopia Statements
  -> open extraction / ontology alignment / resolution
  -> bitemporal graph
  -> exact, BM25, pgvector, RRF and graph context
```

Exact replay retains the same document identity and serialized Statements.
Source corrections and lifecycle changes retain document identity while changing
the source-content checksum. Historical v1 Statements IDs are never silently
migrated to v2; existing sources need an explicit reconciliation plan.

## Technology stack

| Technology | Responsibility |
| --- | --- |
| Rust | Authenticated Utopia API, workers, model clients, graph/materialization and retrieval runtime |
| Python | SOC contracts, normalization, deterministic extraction, adapters, CLIs and offline evaluation |
| PostgreSQL 16 | Authorization, documents, ontology, bitemporal facts, jobs and optional identity registry |
| pgvector | Dense indexes and vector search in the live Rust path |
| Tantivy | Current full-text/BM25 index |
| React + TypeScript | Utopia operator UI for settings, library, ontology, review, graph and history |
| Docker Compose | Existing-lab and isolated source-build orchestration with separate volumes |
| OpenAI-compatible APIs | Workspace-configured Rust Chat/Embedding; optional Python evaluation adapters |
| DistilBERT CPU NER | Optional local English proposal generator, disabled by default |
| Utopia | Upstream-derived graph, retrieval, authorization and UI foundation |
| Graphify | Local code-analysis aid only; not a runtime dependency |

## Safe local workflow

The existing lab is loopback-bound to API/UI `1516` and PostgreSQL `1517`.
Preserve its KB and volumes. The source-build project uses API/UI `2516`,
PostgreSQL `2517`, project name `soorin-sprint1`, and separate named volumes.

Run the no-network foundation gates:

```bash
python3 -m compileall -q soorin
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
python3 -m soorin.e2e.local_validation --report /tmp/soorin-e2e-offline.json
```

Validate Compose without starting services:

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.build.yml --profile app config --quiet
```

Then follow [local development](docs/soorin/LOCAL_DEVELOPMENT.md), [pre-build
validation](docs/soorin/PREBUILD_VALIDATION.md), and the [isolated E2E
runbook](docs/soorin/LOCAL_E2E_VALIDATION.md). Never point database-backed tests
or the E2E harness at the existing lab.

## Models, privacy, and retrieval

Live Rust Chat and Embedding are configured only through authenticated Utopia
Workspace Settings. Python `SOORIN_*` variables configure development/evaluation
adapters and do not activate Rust inference.

- `BAAI/bge-m3` at 1024 dimensions is an evaluation candidate, not a deployed
  or validated model. Changing the model/dimension is not a proven full document
  reindex because `chunks.embedding` does not record model identity.
- `bnsapa/cybersecurity-ner` is pinned to reviewed revision
  `1ad52f1a7686a58da2a427c0706d8b868df47181`, CPU-only, local-files-only,
  disabled by default, and never authoritative.
- Sensitive external inference fails closed without a deployment-owned route
  verifier. Synthetic traffic is allowed only when deployment test mode is on.
- Utopia's live retrieval remains Tantivy + pgvector + RRF. Python retrieval is
  bounded reference/evaluation code; native reranking is deferred.

See [model configuration](docs/soorin/MODEL_CONFIGURATION.md), [CPU NER](docs/soorin/CPU_CYBER_NER.md), [outbound privacy](docs/soorin/OUTBOUND_PRIVACY.md), and [retrieval](docs/soorin/RETRIEVAL_AND_RERANKING.md).

## SOC and NOC use cases

- Join alerts, notables, source events, hosts, users, IP scopes, rules, cases,
  tickets, techniques, and evidence without collapsing their identities.
- Ask what was true at world time `at` and what was known by `as_of`.
- Retrieve prior evidence and graph neighborhoods for analyst context.
- Track corrections, state changes, supersession, and late arrival while keeping
  source provenance recoverable.
- Reuse the same contract/identity rules for NOC observability sources after
  adding an explicitly versioned domain mapping.

## Known restrictions and roadmap

Before merge or production data, the project still requires Cargo format/check/
workspace tests, PostgreSQL migration tests, isolated source-image build, live
ontology/Statements/graph/temporal acceptance, real CPU NER validation, and
approved provider checks. Historical Tantivy recall is incomplete for text that
was replaced after the requested `as_of` time.

Future Agentic SOC work includes a versioned Kafka/Splunk transport, tenant-to-KB
authorization, one atomic registry/materialization boundary, Privacy Gateway
attestation, read-only Auto-Triage/Copilot context tools, monitoring, and
controlled write-back. None is presented as active today.

## Documentation

The [documentation index](docs/soorin/README.md) links the architecture, source
contract audit, ontology/identity/temporal model, deployment runbooks, testing
evidence, implementation report, and release gates.

## License and attribution

The Utopia-derived implementation is distributed under the bundled
[Apache-2.0 license](LICENSE). Preserve upstream copyright and license notices.
The original documentation remains in [README.upstream.md](README.upstream.md).

---

<div align="center">

**Soorin Temporal Knowledge Graph** · Security knowledge with identity, evidence, and time.

</div>
