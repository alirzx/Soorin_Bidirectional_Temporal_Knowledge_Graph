# Soorin SOC knowledge architecture

Soorin TKG is an independent knowledge service built on Utopia. Utopia owns
authenticated APIs, bitemporal graph persistence, ontology alignment, jobs,
search indexes, model settings, and the React UI. Soorin adds the SOC contract,
normalization, deterministic identity and extraction policies, Statements
projection, synthetic evaluation, and future Agentic SOC compatibility.

The diagrams distinguish runtime-active Utopia components from Python
development/evaluation components and future connections.

## 1. Complete SOC knowledge flow

```mermaid
flowchart TB
    A[Splunk / Agentic SOC]:::future -->|future live connector; not implemented| B[llm_payload normalization]
    X[Synthetic SOC fixtures]:::offline --> B
    B --> C[SecurityKnowledgeEvent v1]
    C --> D[Entity extraction]
    D --> D1[Deterministic structured parser]:::offline
    D --> D2[Optional CPU NER proposals]:::optional
    D1 --> E[Canonical identity policy]
    D2 -->|review-only; never overrides IDs| E
    E --> F[Evidence and temporal contracts]
    F --> G[Statements adapter]
    G -->|authenticated source push| H[Utopia Statements API]:::runtime
    H --> I[Open extraction and ontology alignment]:::runtime
    I --> J[Utopia entity resolution]:::runtime
    J --> K[Temporal knowledge graph]:::runtime
    K --> L[Hybrid retrieval / GraphRAG]:::runtime

    classDef runtime fill:#d9f2e6,stroke:#177245,color:#102820;
    classDef offline fill:#e8eefc,stroke:#3559a8,color:#17233d;
    classDef optional fill:#fff2cc,stroke:#a67c00,color:#3d3000;
    classDef future fill:#f3e5f5,stroke:#7b3f8c,color:#32183a,stroke-dasharray:5 5;
```

Python modules are libraries and CLIs; no Python sidecar is deployed. The first
live validation runs the normalizer externally and pushes bounded Statements to
an isolated Utopia source.

## 2. Representative SOC ontology

```mermaid
flowchart LR
    A[SecurityAlert] -->|CORRELATED_WITH| N[SplunkNotable]
    A -->|SUPPORTED_BY| E1[SecurityEvent]
    A -->|DETECTED_BY| R[DetectionRule]
    A -->|OBSERVED_ON| H[Host]
    A -->|ORIGINATED_FROM| IP[IPAddress]
    A -->|INVOLVES_USER| U[UserAccount]
    A -->|MAPPED_TO_TECHNIQUE| M[MITRETechnique]
    A -->|SUPPORTED_BY| EV[EvidenceReference]
    A -->|PART_OF_CASE| C[SOCCase]
    A -->|TRACKED_BY_TICKET| T[Ticket]
    H -->|HAD_IP| IP
```

The complete declaration contains 17 entity types and 15 relation types.
`SecurityAlert`, `SplunkNotable`, and `SecurityEvent` are separate identities;
correlation never means identity. Domain/range, temporal, inverse, and supported
cardinality fields are stored in Utopia. Provenance/confidence policies and
expected relation attributes also require adapter and acceptance-test checks;
the YAML declaration alone is not a universal database constraint.

## 3. Bitemporal lifecycle

```mermaid
flowchart LR
    O[Initial observation] -->|new source identity| N[New occurrence]
    N -->|same checksum| R[Exact replay: unchanged]
    N -->|same source ID; corrected content| C[Correction]
    C -->|lifecycle field changed| S[State change]
    N -->|event arrives after newer knowledge| L[Late arrival]
    N --> Q[Historical query]
    C --> Q
    S --> Q
    L --> Q
    Q --> W[at = world time]
    Q --> K[as_of = knowledge time]
```

World time says when a fact applied; knowledge time says when Utopia knew it.
Delivery and processing timestamps do not create source-content revisions.
Utopia owns ledger `recorded_at`/`invalidated_at`; the adapter maps source event
time to Statements and never fabricates ledger time. Exact replay still needs a
live `unchanged` observation in the isolated lab.

## 4. Models and retrieval

```mermaid
flowchart TB
    WS[Authenticated Workspace Settings]:::runtime --> CHAT[Rust Chat client]:::runtime
    WS --> EMB[Rust Embedding client]:::runtime
    EMB --> PG[(pgvector)]:::runtime
    BM[Tantivy BM25]:::runtime --> RRF[RRF fusion]:::runtime
    PG --> RRF
    RRF --> CTX[Knowledge Context / GraphRAG]:::runtime

    PY[Python model profiles]:::offline --> PH[Health and evaluation adapters]:::offline
    PH --> PE[Bounded embedding evaluation]:::offline
    PH --> PR[Optional cross-encoder reranker]:::optional
    RRF -. future native integration .-> PR
    PR -. future reviewed context .-> CTX

    classDef runtime fill:#d9f2e6,stroke:#177245,color:#102820;
    classDef offline fill:#e8eefc,stroke:#3559a8,color:#17233d;
    classDef optional fill:#fff2cc,stroke:#a67c00,color:#3d3000;
```

Workspace Settings are authoritative for live Rust Chat and Embedding. Python
`SOORIN_*` variables do not configure that runtime. The Rust path runs Tantivy
and pgvector in parallel and fuses bounded channel results with RRF. The Python
retrieval layer is an offline reference with bounded candidates/cache; the
reranker is not connected to native retrieval.

## 5. Isolated deployment

```mermaid
flowchart LR
    subgraph EXISTING[Existing Utopia / Soorin SOC Lab - preserve]
        EAPI[API and UI 127.0.0.1:1516] --> EDB[(PostgreSQL 127.0.0.1:1517)]
        EDB --> EV[(existing named volumes)]
    end

    subgraph SOURCE[Soorin source-build lab - isolated]
        SAPI[Source-built API and UI 127.0.0.1:2516] --> SDB[(PostgreSQL 127.0.0.1:2517)]
        SDB --> SV[(soorin-sprint1 volumes)]
        CLI[Python normalizer / E2E CLI] -->|synthetic Statements only| SAPI
    end

    EXISTING ~~~ SOURCE
```

The projects share no database or persistent volume. Registration is disabled
after isolated bootstrap, ports are loopback-bound, and the E2E harness rejects
port `1516`. Safe shutdown omits `--volumes`.

## Ownership and trust boundaries

- Agentic SOC owns operational alert/case state until a versioned connector is
  implemented.
- Splunk and other source systems own source-observed events and identifiers.
- Soorin contracts define cross-system semantics, source identity, evidence,
  replay, and conservative canonical-key rules.
- Utopia owns authenticated materialization, ontology persistence, bitemporal
  facts, retrieval indexes, and operational UI.
- Model output is a review proposal. It cannot override authoritative source
  identity or analyst decisions.
- External Chat, Embedding, and Reranking share one fail-closed outbound policy.
  Sensitive production text requires a deployment-owned verifier attestation;
  a caller boolean is not proof of Privacy Gateway traversal.

The persistent identity registry exists behind migrations `0111` and `0112`,
but no active ingestion caller uses it. Foundation deliberately keeps it dormant
until Sprint 2 can activate registration, conflict handling, Statements render,
and Utopia entity binding in one authenticated transaction boundary.
