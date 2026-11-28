<div align="center">

<img src="assets/soorinsec-logo2.png" alt="Soorin Security" width="288">

# Soorin Temporal Knowledge Graph

**A temporal, evidence-grounded knowledge layer for security operations and AI agents.**

Connect security alerts, identities, assets, investigations, and evidence in a consistent knowledge graph. Explore what happened, how entities are related, and what was known at any point in time.

[![CI](https://github.com/alirzx/Soorin_Bidirectional_Temporal_Knowledge_Graph/actions/workflows/checks.yml/badge.svg?branch=main)](https://github.com/alirzx/Soorin_Bidirectional_Temporal_Knowledge_Graph/actions/workflows/checks.yml)
[![Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-315a71)](LICENSE)

[**Architecture**](docs/soorin/PRODUCTION_ARCHITECTURE.md) · [**API & ingestion**](docs/soorin/MANUAL_SOC_INGESTION.md) · [**Search & GraphRAG**](docs/soorin/RETRIEVAL_AND_RERANKING.md) · [**Integrations**](docs/soorin/AGENTIC_SOC_INTEGRATION_V1.md) · [**Documentation**](docs/soorin/README.md)

</div>

## Overview

Security knowledge rarely lives in one place. SIEM events, notable alerts, investigation records, infrastructure inventories, and analyst findings contain related facts but use different identifiers, timestamps, and evidence formats.

**Soorin TKG** provides an independent knowledge service for bringing these records together without losing their source authority or history. Its provenance-first design distinguishes an exact identity match from a relevant search result, and an evidence-backed fact from a generated interpretation.

Built on the [Utopia graph foundation](README.upstream.md), Soorin adds SOC-oriented data contracts, a reviewed security ontology, deterministic normalization, durable identity resolution, bitemporal knowledge, and agent-accessible retrieval.

## Core capabilities

| Capability | What it enables |
|---|---|
| **Canonical security identities** | Resolve and link alerts, hosts, IP addresses, users, detections, cases, and other entities through governed source authority rather than name similarity alone. |
| **Temporal knowledge** | Reconstruct valid-time and knowledge-time perspectives across evolving observations, corrections, and investigations. |
| **Evidence-backed relationships** | Preserve typed facts, source-document versions, provenance, and citations for traceable reasoning. |
| **SOC event ingestion** | Preview and ingest supported curated or canonical security records with durable receipts and asynchronous materialization. |
| **Hybrid retrieval** | Combine exact identity resolution, Tantivy BM25, pgvector-based semantic recall, and optional relevance reranking. |
| **Agent and application access** | Expose scoped knowledge through REST APIs, MCP tools, and the React operator interface. |
| **Governed AI assistance** | Use local CPU embedding and reranking services, review-only entity proposals, and explicit privacy controls for external model calls. |

The [SOC ontology](docs/soorin/SOC_ONTOLOGY.md) defines security-focused entity types, relationships, and constraints. Knowledge bases, source bindings, and access controls keep the data lifecycle explicit.

## System architecture

```mermaid
flowchart LR
    subgraph PRODUCERS["Security data producers"]
        SIEM["SIEM and Splunk alerts"]
        CURATED["Curated SOC records"]
        CANONICAL["Canonical knowledge events"]
    end
    subgraph INGEST["Source-governed ingestion"]
        PREVIEW["Preview and normalize"]
        AUTH["Authenticate source and KB scope"]
        RECEIPT["Durable receipt and job queue"]
    end
    subgraph GRAPH["Temporal knowledge engine"]
        IDENTITY["Canonical identity resolution"]
        ONTOLOGY["Reviewed ontology"]
        FACTS["Typed facts and provenance"]
    end
    subgraph DATA["Persistent knowledge"]
        POSTGRES[("PostgreSQL and pgvector")]
        TANTIVY[("Tantivy BM25 index")]
    end
    subgraph READ["Knowledge retrieval APIs"]
        EXACT["Exact identity lookup"]
        HYBRID["Lexical and semantic search"]
        CONTEXT["Temporal graph context"]
    end
    subgraph CLIENTS["Authorized applications"]
        UI["Operator UI"]
        API["REST and MCP"]
        AGENTS["Agentic_SOC and other agents"]
    end
    SIEM --> PREVIEW
    CURATED --> PREVIEW
    PREVIEW --> AUTH
    CANONICAL --> AUTH
    AUTH --> RECEIPT
    RECEIPT --> IDENTITY
    ONTOLOGY --> FACTS
    IDENTITY --> FACTS
    FACTS --> POSTGRES
    FACTS --> TANTIVY
    POSTGRES --> EXACT
    POSTGRES --> HYBRID
    POSTGRES --> CONTEXT
    TANTIVY --> HYBRID
    EXACT --> API
    HYBRID --> API
    CONTEXT --> API
    API --> UI
    API -.-> AGENTS
    MODELS["Optional CPU embedding and reranking"] -.-> HYBRID
    classDef producer fill:#eff6ff,stroke:#3976ac,color:#183b5b
    classDef engine fill:#e8f5ed,stroke:#32805b,color:#194c37
    classDef persistence fill:#f3effd,stroke:#7d6da7,color:#3c3062
    classDef consumer fill:#fff3e5,stroke:#b88945,color:#5d421e
    class SIEM,CURATED,CANONICAL producer
    class AUTH,RECEIPT,IDENTITY,ONTOLOGY,FACTS engine
    class POSTGRES,TANTIVY persistence
    class UI,API,AGENTS consumer
```

**PostgreSQL** is the authoritative knowledge ledger; **Tantivy** is a rebuildable lexical index, and **pgvector** supports semantic recall. Curated records are previewed and normalized before admission, while already-canonical events use their dedicated authenticated contract. Identity is established by source authority, not search similarity. REST and MCP expose scoped knowledge without direct database access.

For deployment boundaries and component design, see [Production Architecture](docs/soorin/PRODUCTION_ARCHITECTURE.md) and [Knowledge Architecture](docs/soorin/SOC_KNOWLEDGE_ARCHITECTURE.md). For data contracts and temporal semantics, see [Manual SOC Ingestion](docs/soorin/MANUAL_SOC_INGESTION.md) and [Temporal Model](docs/soorin/TEMPORAL_MODEL.md).

## From an alert to grounded knowledge

```mermaid
sequenceDiagram
    autonumber
    participant P as SOC producer
    participant A as Soorin API
    participant J as Knowledge jobs
    participant G as Temporal graph
    participant R as Authorized reader

    P->>A: Preview curated record
    A-->>P: Canonical event and validation
    P->>A: Ingest approved record
    A-->>P: Durable receipt
    A->>J: Queue materialization
    J->>G: Link identities and bind evidence
    P->>A: Check receipt status
    A-->>P: Bound or explicit processing state
    R->>A: Search, resolve, or request context
    A->>G: Retrieve scoped facts and evidence
    A-->>R: Results with provenance and citations
```

Ingestion is asynchronous: a receipt confirms that a record has been accepted for processing; a **bound** receipt confirms that the expected materialization checks have completed. Search, exact identity resolution, and temporal context serve distinct purposes.

For the complete event envelopes, authentication rules, response schemas, retries, and error handling, consult the [Ingestion Guide](docs/soorin/MANUAL_SOC_INGESTION.md), [Curated HTTP Contract](soorin/contracts/schemas/curated_http_v1.openapi.json), and [Identity Resolution](docs/soorin/ENTITY_RESOLUTION.md).

## Integration surfaces

The following are selected endpoints; paths are relative to `/api/v1`.

| Workflow | Endpoint |
|---|---|
| Preview a curated SOC alert | `POST /sources/{source_id}/soc/preview` |
| Submit a curated SOC alert | `POST /sources/{source_id}/soc/ingest` |
| Submit a canonical SOC event | `POST /sources/{source_id}/knowledge-events` |
| Check ingestion progress | `GET /kbs/{kb_id}/knowledge/receipts/{receipt_id}` |
| Resolve a source-backed identity | `POST /kbs/{kb_id}/knowledge/resolve` |
| Search indexed knowledge | `POST /kbs/{kb_id}/search` |
| Retrieve graph facts and evidence | `POST /kbs/{kb_id}/knowledge/context` |
| Inspect the knowledge graph | `GET /kbs/{kb_id}/graph/overview` |
| Access knowledge tools | `POST /kbs/{kb_id}/mcp` |

Curated SOC ingestion uses a documented versioned source profile; it is not a generic, schema-free JSON endpoint. Read and write clients use different scoped credentials. Retrieval metadata identifies which lexical, dense, and reranking stages were actually executed.

The optional SOC receipt reconciler polls a payload-free status route with a KB-scoped receipt PAT. Investigation clients continue to use a separate scoped reader PAT. [Agentic_SOC integration](docs/soorin/AGENTIC_SOC_INTEGRATION_V1.md)

Soorin TKG is independently deployable. **Agentic_SOC** and other investigation systems can integrate as event producers and evidence consumers through these interfaces without sharing the graph database directly.

See [Producer Mapping](docs/soorin/PRODUCER_MAPPING_V1_20261115.md), [Agentic_SOC Integration](docs/soorin/AGENTIC_SOC_INTEGRATION_V1.md), [Agent Tool Contracts](docs/soorin/AGENT_TOOL_CONTRACTS.md), and [Retrieval & Reranking](docs/soorin/RETRIEVAL_AND_RERANKING.md).

## Deploy and operate

The repository separates application, model-runtime, and database concerns and provides distinct configurations for development and controlled deployment. Model artifacts, secrets, persistent volumes, and service access are managed outside the source tree.

Build from a reviewed source revision on a local host or Server 55 with isolated CPU embedding and reranking. [Source deployment and rollback](docs/soorin/SOURCE_DEPLOYMENT.md)

Start with [Local Development](docs/soorin/LOCAL_DEVELOPMENT.md) for an engineering environment or [Deployment & Operations](docs/soorin/PRODUCTION_DEPLOYMENT.md) for the documented deployment, configuration, security, backup, and recovery requirements.

## Documentation

| Topic | Reference |
|---|---|
| **Architecture and design** | [Production Architecture](docs/soorin/PRODUCTION_ARCHITECTURE.md) · [Knowledge Architecture](docs/soorin/SOC_KNOWLEDGE_ARCHITECTURE.md) |
| **Ingestion and API contracts** | [Manual SOC Ingestion](docs/soorin/MANUAL_SOC_INGESTION.md) · [OpenAPI Schema](soorin/contracts/schemas/curated_http_v1.openapi.json) |
| **Identity and temporal semantics** | [Identity Resolution](docs/soorin/ENTITY_RESOLUTION.md) · [Temporal Model](docs/soorin/TEMPORAL_MODEL.md) · [SOC Ontology](docs/soorin/SOC_ONTOLOGY.md) |
| **Search and agent tools** | [Retrieval & Reranking](docs/soorin/RETRIEVAL_AND_RERANKING.md) · [Agent Tool Contracts](docs/soorin/AGENT_TOOL_CONTRACTS.md) |
| **Production** | [Hardened Compose and compatibility](docs/soorin/SERVER55_PRODUCTION_RELEASE.md#canonical-hardened-production-interface) |
| **Integrations** | [Agentic_SOC](docs/soorin/AGENTIC_SOC_INTEGRATION_V1.md) · [Source Mapping](docs/soorin/PRODUCER_MAPPING_V1_20261115.md) |
| **Models, security, and operations** | [Model Configuration](docs/soorin/MODEL_CONFIGURATION.md) · [Security Boundaries](docs/soorin/SECURITY_BOUNDARIES.md) · [Deployment](docs/soorin/PRODUCTION_DEPLOYMENT.md) |
| **Engineering validation** | [Testing & Evaluation](docs/soorin/TESTING_AND_EVALUATION.md) · [Engineering Documentation Index](docs/soorin/README.md) |

## License and acknowledgments

Licensed under [Apache-2.0](LICENSE). Soorin TKG builds on the [Utopia](README.upstream.md) project; the original notices and upstream documentation are preserved.
