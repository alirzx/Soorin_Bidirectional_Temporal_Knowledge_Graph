# Soorin TKG: architecture baseline (October 2026)

## Stage 0: verified local topology

```text
Browser (127.0.0.1:1516)
  -> Utopia rc9 HTTP API + embedded UI
  -> PostgreSQL 16 / pgvector (Docker volume)
  -> data/files + data/index + data/secret.key (bind mount)
  -> asynchronous ingest/extract/align/review workers
```

The current Docker app runs a **prebuilt upstream rc9 image**. Changing Rust/React source in this repository does **not** change the running container until the application is rebuilt or a Soorin image is deployed.

## Stage 1: SOC lab flow (synthetic)

```text
Splunk-style synthetic records (JSON fixtures)
  -> field-aware normalization (event/notable/alert/case/Jira)
  -> e/s/n open statement documents + stable external_id
  -> POST /api/v1/sources/{id}/statements
  -> source/document ingestion and asynchronous graph extraction
  -> open graph
  -> ontology phrase/kind alignment + temporal processing
  -> typed graph (when alignment succeeds)
  -> authenticated Graph UI / graph API
```

The **Statements** API is not a direct typed-graph write API. This lab deliberately tests supported Utopia rc9 public contracts, not an invented graph insertion endpoint. A 200 response with `action=created` confirms ingestion only.

## Intended integration (not implemented)

```text
Splunk / SOC Kafka topic -> durable adapter + validation + DLQ
  -> Soorin TKG write interface with tenant-scoped IDs and provenance
  -> temporal ledger / graph query service
  -> Agentic SOC ContextBundle (shadow read mode initially)
  -> Tier-1 / Tier-2 investigation support
```

The original Agentic SOC system already stores alerts in PostgreSQL, event evidence in Splunk/ClickHouse, and has an existing Neo4j projection. Do not replace these on day one. Large raw log bodies remain in their source stores; the graph should link stable evidence IDs, not duplicate entire log streams.

## Identity and temporal requirements

- Never merge `src_ip`, user, or hostname **across tenants** just because display text matches.
- Host/IP ownership changes over time; graph relationships require world-time `valid_from/valid_to`, and audit history requires knowledge-time `recorded_at/invalidated_at`.
- Source `external_id` is deterministic and replayable; identical replay should return `unchanged`.
- Store provenance (source system, source ID, index, search SID, event ID, timestamp). The mock uses only basic qualifiers, not a production provenance schema.
- Treat event-time UTC and ingest-time UTC independently; test late and out-of-order arrivals later.
- Restrict source tokens and redact secrets; the remote data privacy gateway is for outgoing LLM calls and does not substitute for tenant isolation in the graph store.

## P0 gates before a SOC integration PR

1. Source token auth, rejected malformed requests, replay behavior.
2. Document processing, graph counts, actual evidence edges, and failure queues.
3. Tenant isolation, deterministic identity across repeated events, duplicate hostnames, NAT/shared IPs.
4. Temporal queries (`at`, `as_of`), late events, and interval closure semantics.
5. Backpressure / retry / DLQ / idempotent Kafka consumer with zero silent drop.
6. Local resources and recovery: backups of **both DB and data directory**, including `secret.key`.
