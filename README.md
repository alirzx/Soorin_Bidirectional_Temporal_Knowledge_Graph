<div align="center">

![Soorin Temporal Knowledge Graph banner](assets/banner.webp)

# Soorin Temporal Knowledge Graph

**Temporal security intelligence · Provenance-aware knowledge · Graph retrieval foundations**

A standalone, extensible knowledge service for organizing security entities, relationships, evidence, and historical state. Designed to become a reusable knowledge layer for **Soorin Agentic SOC** and other Soorin products.

[Architecture](docs/soorin/SOC_KNOWLEDGE_ARCHITECTURE.md) · [Getting started](docs/soorin/LOCAL_DEVELOPMENT.md) · [Sprint 1 status](docs/soorin/SPRINT1_IMPLEMENTATION_REPORT.md) · [Documentation](docs/soorin/README.md)

</div>

> [!IMPORTANT]
> **Development status: Sprint 1 foundation, not production-ready.** The baseline Utopia server and synthetic Statements lab have been exercised. The new SOC-specific Python contracts, identity/extraction, model adapters, and retrieval evaluation are implemented and tested offline. They are **not automatically wired into the running Rust API or React UI**. Live model, typed ontology, historical revision, and full Rust regression validation remain open.

## Product vision

Soorin TKG is being developed as an **independent knowledge-graph service**, with Agentic SOC as its initial target consumer. Its eventual responsibility is to make security facts, prior alerts and notable events, investigative context, and evidence **identifiable, queryable, time-aware, and traceable to sources**. SOC detection, Fusion, Auto-Triage decisions, and agent orchestration remain owned by Agentic SOC.

The intended data flow is:

```text
Splunk and SOC data (future live integration)
    -> canonical, tenant-scoped knowledge event
    -> deterministic entities + evidence + temporal facts
    -> Utopia Statements / ontology / graph processing
    -> PostgreSQL + pgvector + Tantivy
    -> graph + exact + semantic + temporal retrieval
    -> evidence-backed context for Auto-Triage, Copilot and other agents
```

**Currently implemented:** the synthetic SOC lab, standardized contracts, normalization, ontology importer, identity-key generation, offline temporal checks, and reusable model/retrieval adapters. **Not yet implemented:** live Kafka/Splunk ingestion, a persistent cross-system identity registry, native runtime reranking, and Agentic SOC agent connections.

## Capabilities and verified boundaries

| Area | Current capability | Evidence / remaining gate |
| --- | --- | --- |
| **Temporal graph core** | Utopia bitemporal graph and source-revision semantics | Live SOC revision + `at`/`as_of` acceptance test pending |
| **SOC data contracts** | Versioned `soorin.soc.knowledge-event.v1` and JSON Schema | Offline tests pass; replay/content identity needs hardening |
| **SOC ontology** | 17 entity types; 15 relation types; guarded preview/apply importer | Live isolated-KB import and semantic constraint validation pending |
| **Identity & extraction** | Tenant-scoped deterministic keys; structured Splunk/OCSF extraction | Persisted identity mapping and false-merge tests pending |
| **Evidence & provenance** | Source references, qualifiers, evidence contract | Full evidence projection and round-trip verification pending |
| **Chat / embedding** | Configurable OpenAI-compatible Python adapters and fake-provider tests | Runtime Utopia Workspace Settings and real provider validation pending |
| **Retrieval & reranking** | Offline exact, BM25, dense, RRF, optional reranker adapters | Production retrieval remains in Rust; native reranking not connected |
| **UI** | Original Utopia React UI for KBs, graph, ontology, search and settings | No Sprint 1 Soorin-specific UI changes |
| **Agentic SOC integration** | Source-contract research and future-facing designs | Live pipeline and agent reads are outside Sprint 1 |

This table intentionally distinguishes **implemented code**, **tested functionality**, and **future integration**.

## Architecture

The deployed core is based on **Utopia v0.1.0-rc9**:

```text
             Utopia API + React UI
                     |
    +----------------+----------------+
    |                |                |
 Statements       Ontology         Graph / Search
 ingestion        alignment         & history
    |                |                |
    +----------------+----------------+
                     |
        PostgreSQL 16 + pgvector
             Tantivy index
                     |
       Soorin Sprint 1 Python modules
    contracts · extraction · identity
    temporal · adapters · model checks
              offline retrieval
```

**Implementation boundary:** the Soorin Python modules are development/compatibility components today. They are not presented as live endpoints in the upstream rc9 image. See the [architecture audit](docs/soorin/SPRINT1_ARCHITECTURE_AUDIT.md) and [known gaps](docs/soorin/SOC_FOUNDATION_GAP_ANALYSIS.md).

## Quick start

### 1. Protect the existing lab

The previously verified local lab uses the upstream rc9 container on `127.0.0.1:1516` and PostgreSQL on `127.0.0.1:1517`. It holds the **Soorin SOC Lab** knowledge base. Do not reset its database volumes or assume source edits affect that prebuilt image.

```bash
docker compose -f docker-compose.local.yml --profile app ps
curl -fsS http://127.0.0.1:1516/api/v1/health
```

For a **separate source-build environment**, use [the isolated development guide](docs/soorin/LOCAL_DEVELOPMENT.md), which defines ports `2516`/`2517` and independent named volumes.

### 2. Validate the synthetic SOC pipeline without credentials

```bash
python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
```

The baseline fixture contains **nine synthetic SOC records and 122 open Statements**. A second fixture contains **ten synthetic `llm_payload` scenarios**. The small offline retrieval benchmark is not a production quality benchmark.

### 3. Test Statements ingestion (optional)

Create a **Statements** source in an intentionally selected test knowledge base and follow the [local smoke runbook](docs/soorin/local-smoke.md). The API uses a source UUID and its own ingest token:

```text
POST /api/v1/sources/{source_id}/statements
```

A successful `created` action confirms document ingestion, **not** completed ontology alignment or typed-graph materialization. Check document status, jobs, Ontology/Review, and graph queries separately. Never commit a token or private SIEM data.

## AI models and search

The **running Utopia Rust service** owns Chat/Embedding inference through authenticated Workspace Settings. Sprint 1 adds **Python configuration, OpenAI-compatible embedding/health adapters, and optional reranker adapters** for compatibility tests and evaluation.

- **Chat LLM:** provider-agnostic OpenAI-compatible setting; no live provider was configured by Sprint 1.
- **Embedding:** configurable model and dimensions. `BAAI/bge-m3` (1024 dense dimensions) is an **evaluation candidate**, not a validated deployed model.
- **Reranker:** Cohere v2, Jina v1 and TEI-compatible Python adapters; **disabled by default and not wired to Utopia Rust retrieval**.
- **Retrieval:** the existing Utopia core uses Tantivy BM25 + pgvector with RRF. The Soorin Python reference layer evaluates exact, BM25, dense, hybrid and reranking over in-memory synthetic documents.

Read [model configuration](docs/soorin/MODEL_CONFIGURATION.md) and [retrieval boundaries](docs/soorin/RETRIEVAL_AND_RERANKING.md) before setting any `SOORIN_*` variable.

## Quality gates and known limitations

Sprint 1's recorded offline results were **61 Python foundation tests**, **7 existing mock-Splunk tests**, **268 frontend tests**, TypeScript checks, frontend build and Compose validation. These were reported from the development environment and are **not CI or independent live-backend verification**.

The following remain open:

1. Stable replay/content checksums independent of processing time.
2. Correct separation of source events, Splunk notables and SOC alert identities.
3. Cross-document canonical identity and safe tenant/network scoping.
4. Semantic ontology compatibility and complete evidence-provenance projection.
5. Isolated live KB tests for ingestion, revisions, typed graph and temporal queries.
6. Rust workspace gates, approved live model checks and actual Utopia runtime configuration.
7. Native reranking, historical full-text recall, scale testing, and production security controls.

See [Sprint 1 gap register](docs/soorin/SOC_FOUNDATION_GAP_ANALYSIS.md) and [testing guide](docs/soorin/TESTING_AND_EVALUATION.md). **Do not merge to `main` until the P0 correctness and live validation gates are addressed.**

## Documentation

Start with the [Soorin documentation index](docs/soorin/README.md), organized into architecture, contracts, ontology/identity, temporal knowledge, models/retrieval, runbooks, and project status. The [Sprint 1 implementation report](docs/soorin/SPRINT1_IMPLEMENTATION_REPORT.md) records what Codex implemented and actually tested.

## Development workflow

- Work on `feature/soc-knowledge-foundation-v1`; keep `main` protected from unreviewed changes.
- Use sanitized, explicitly synthetic fixtures and isolated KBs for integration tests.
- Keep `personal` and Soorin organization `origin` remotes separate; do not push to `upstream`.
- Preserve the original project runtime and its data volumes.
- Keep configurations/keys outside Git; do not confuse Python evaluation `SOORIN_*` settings with Utopia Rust Workspace Settings.

## License and upstream attribution

The underlying Utopia implementation is distributed under the repository's bundled **Apache-2.0 [LICENSE](LICENSE)**. Retain required copyright and license notices. The Soorin repository has an independent Git history, but this does **not** remove upstream attribution obligations. Original documentation is retained in [README.upstream.md](README.upstream.md); its package/binary names remain accurate for the upstream-based runtime until an intentional rebranding and rebuild.

---

<div align="center">

**Soorin Temporal Knowledge Graph** · Security knowledge with identity, evidence, and time.

</div>
