# SOC knowledge architecture

```text
Agentic SOC structured record (future transport)
  -> Splunk/OCSF normalizer
  -> SecurityKnowledgeEvent v1
       | deterministic entities + authoritative IDs
       | temporal facts/revisions
       | evidence references + provenance categories
       v
  -> Statements adapter (dry-run/render/push)
  -> Utopia source/document revision
  -> open statements -> type/phrase alignment -> resolution
  -> typed bitemporal graph
  -> exact / BM25 / pgvector / RRF / optional reranker
  -> provenance-preserving KnowledgeContext
```

## Source-of-truth rules

- Agentic SOC owns operational alert/case state until a future synchronization contract exists.
- Splunk/other source systems own observed event data and source IDs.
- Utopia owns graph persistence, bitemporal facts, authorization, retrieval indexes, and operational UI.
- Soorin contracts own cross-system semantics and deterministic identity rules.
- Model output is an attributed proposal. It cannot override source-observed identity or analyst decisions.

## Contract boundaries

`SecurityKnowledgeEvent` carries schema/tenant/source identity, event/observation/record times, canonical entities, relations, temporal facts, evidence references, attributes, vendor fields, source references, checksum, and optional curated payload version. Deterministic serialization makes replay and revision comparison stable.

The Splunk adapter deliberately separates verified source metadata, reported observations, analyst assertions, inferred relationships, model conclusions, and retrieval hints. This prevents current rule text, allowlists, or investigation queries from becoming false event facts.

## Runtime boundary

No Python API service is added. Python modules validate, normalize, render, benchmark, and provide future integration libraries. Actual graph writes use Utopia's authenticated Statements endpoint. Existing React pages remain the operational UI.

## Security boundary

Tenant ID is part of canonical identity and every retrieval filter. Future production deployment must additionally map SOC tenant authorization to a Utopia workspace/KB boundary. External inference is off by default, uses bounded controlled text, redacts obvious credential fields, validates responses, and requires an approved privacy route.
