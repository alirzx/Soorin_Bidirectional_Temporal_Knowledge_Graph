# Soorin engineering documentation

The native ingestion, persistent identity, typed alignment, bitemporal evidence,
model lineage, reranking and read-only context implementations are in this branch.
Engineering handoff is distinct from production release approval.

| Purpose | Document |
|---|---|
| Current implementation and evidence | [Final acceptance](FINAL_ACCEPTANCE_REPORT.md) |
| Runtime ownership and call paths | [Production architecture](PRODUCTION_ARCHITECTURE.md) |
| SOC data flow | [Knowledge architecture](SOC_KNOWLEDGE_ARCHITECTURE.md) |
| Deployment and rollback | [Production deployment](PRODUCTION_DEPLOYMENT.md) |
| Next controlled acceptance | [Build and test handoff](BUILD_AND_TEST_HANDOFF.md) |
| Security and data minimization | [Security boundaries](SECURITY_BOUNDARIES.md) |
| Agentic_SOC integration | [Integration v1](AGENTIC_SOC_INTEGRATION_V1.md) |
| Source audit | [Agentic_SOC source contracts](AGENTIC_SOC_DATA_CONTRACT_ANALYSIS.md) |
| Identity / temporal behavior | [Identity](ENTITY_RESOLUTION.md), [Temporal model](TEMPORAL_MODEL.md) |
| Ontology | [SOC ontology](SOC_ONTOLOGY.md) |
| Models and artifacts | [Configuration](MODEL_CONFIGURATION.md), [Artifact lifecycle](MODEL_ARTIFACT_MANAGEMENT.md), [CPU NER](CPU_CYBER_NER.md) |
| Privacy and retrieval | [Outbound privacy](OUTBOUND_PRIVACY.md), [Retrieval/reranking](RETRIEVAL_AND_RERANKING.md) |
| Development and tests | [Local development](LOCAL_DEVELOPMENT.md), [Pre-build](PREBUILD_VALIDATION.md), [E2E](LOCAL_E2E_VALIDATION.md), [Evaluation](TESTING_AND_EVALUATION.md) |
| Remaining defects/gates | [Engineering register](ENGINEERING_GAP_REGISTER.md) |
| Upstream changes | [Reconciliation](upstream-sync.md) |

Implemented means source exists. Mock-tested means synthetic contracts passed.
Integration-ready means a documented interface exists but may be unexercised.
Build/model/migration/runtime acceptance remain separate evidence. PASS never
means an omitted or skipped gate succeeded.

Earlier `SPRINT1_*`, foundation gap/capability reports and old lab notes are
historical checkpoints; they do not override current implementation/evidence.
Preserve all existing labs, KBs, caches, Graphify output and database volumes.
