# Soorin TKG · Engineering Documentation

This is the documentation entry point for the **Soorin Temporal Knowledge Graph** product. The project is at **Sprint 1 foundation** stage, not production-ready. The original Utopia runtime/UI and the new Soorin Python modules have different execution and verification boundaries.

## Start here

| Audience / objective | Document |
| --- | --- |
| Product overview, status, and safe quick start | [Project README](../../README.md) |
| System ownership, data flow, graph and SOC boundaries | [Security knowledge architecture](SOC_KNOWLEDGE_ARCHITECTURE.md) |
| Utopia source and API audit | [Sprint 1 architecture audit](SPRINT1_ARCHITECTURE_AUDIT.md) |
| Reused Utopia functionality | [Capability matrix](UTOPIA_CAPABILITY_MATRIX.md) |
| Gaps and release gates | [Foundation gap analysis](SOC_FOUNDATION_GAP_ANALYSIS.md) |
| Exact implementation and test evidence | [Sprint 1 implementation report](SPRINT1_IMPLEMENTATION_REPORT.md) |
| Isolated development environment | [Local development](LOCAL_DEVELOPMENT.md) |
| Reproducible test commands | [Testing and evaluation](TESTING_AND_EVALUATION.md) |
| Exact static/source-build release gates | [Pre-build validation](PREBUILD_VALIDATION.md) |
| Synthetic isolated acceptance harness | [Local E2E validation](LOCAL_E2E_VALIDATION.md) |

## SOC domain and data

- [Agentic SOC data-contract audit](AGENTIC_SOC_DATA_CONTRACT_ANALYSIS.md)
- [`llm_payload` field mapping](LLM_PAYLOAD_FIELD_MAPPING.md)
- [SOC ontology and guarded importer](SOC_ONTOLOGY.md)
- [Canonical identity and ambiguity](ENTITY_RESOLUTION.md)
- [Bitemporal lifecycle and revision semantics](TEMPORAL_MODEL.md)
- [Splunk and SOC mapping](splunk-mapping.md)
- [Future agent compatibility, not runtime integration](FUTURE_AGENT_COMPATIBILITY.md)

## Models, retrieval and operations

- [Model configuration, including runtime versus Python-only settings](MODEL_CONFIGURATION.md)
- [Outbound model privacy and gateway attestation boundary](OUTBOUND_PRIVACY.md)
- [Optional local CPU cybersecurity NER](CPU_CYBER_NER.md)
- [BM25/vector search, reranking and known history limitations](RETRIEVAL_AND_RERANKING.md)
- [Existing SOC lab smoke test](local-smoke.md)
- [Upstream maintenance and remotes](upstream-sync.md)

## Verification terminology

- **Implemented:** code exists in this repository.
- **Offline-tested:** deterministic, fake-transport or local fixtures passed. No live Utopia database or model has necessarily been exercised.
- **Runtime-active:** feature is used by the running Rust server/API or UI.
- **Blocked / pending:** not validated, and must not be reported as passing.

The existing rc9 UI on `127.0.0.1:1516` and its lab KB must not be reset. The isolated source-build Compose uses `2516`/`2517` with different volumes, but the source build and live tests are still pending.

## Evidence and release gates

The Sprint 1 source contracts, identity utilities, extraction and adapters are offline-tested. **Do not merge to `main` or claim SOC integration readiness** until the P0 gaps and the isolated live ontology/Statements history experiments are resolved and Rust checks pass. External model endpoints must be assessed for SOC privacy before sending organizational content.

The baseline mock (9 records), `llm_payload` corpus (10 scenarios), and isolated
E2E lifecycle fixture are explicitly synthetic regression inputs, not production
data. The E2E fixture includes an offline cross-tenant assertion; live mode
pushes only the isolated `tenant-blue` rows.
