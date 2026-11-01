# Soorin Bidirectional Temporal Knowledge Graph

An independent Soorin engineering repository for temporal security knowledge, provenance-aware graph retrieval, and eventual integration with Agentic SOC. The initial implementation is based on **Utopia v0.1.0-rc9**, with a new Soorin root commit and a separately maintained upstream remote.

## Local status and scope

- Baseline: Rust Utopia server, PostgreSQL + pgvector, embedded Tantivy index, React UI.
- Local deployment: `docker compose -f docker-compose.local.yml --profile app up -d`.
- Health: `curl -fsS http://127.0.0.1:1516/api/v1/health`.
- Lab knowledge base: **Soorin SOC Lab** (create/select this in the UI; it is database state, not Git data).
- First integration: synthetic Splunk ES notables, fused alerts, Windows Security events, SOC case, and Jira ticket.
- Sprint 1 delivers versioned SOC contracts, a validated ontology/importer,
  deterministic tenant-aware identity, structured extraction, temporal revision
  semantics, Statements compatibility, configurable model adapters, retrieval
  and evaluation foundations. Live Agentic SOC ingestion remains out of scope.

## First SOC ingestion test

See [the mock lab guide](soorin/tests/mock_splunk/README.md) and [the local smoke checklist](docs/soorin/local-smoke.md).

```bash
python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
# After creating a Statements source in the Soorin SOC Lab KB:
export UTOPIA_SOURCE_ID='<source-uuid>'
# Zsh:
read -rs 'UTOPIA_INGEST_TOKEN?Utopia source token: '; echo
export UTOPIA_INGEST_TOKEN
python3 soorin/tests/mock_splunk/scripts/soc_mock.py push
unset UTOPIA_INGEST_TOKEN
```

The push endpoint is `POST /api/v1/sources/{source_id}/statements` using a source ingest token. `created` means the statement document was ingested, **not** that aligned typed edges have already been materialized. Inspect Library, Graph, Ontology, Review and job logs separately.

## Engineering documentation

- [Architecture and source-of-truth boundaries](docs/soorin/architecture.md)
- [Splunk and Agentic SOC field mapping](docs/soorin/splunk-mapping.md)
- [Local deployment, tests and troubleshooting](docs/soorin/local-smoke.md)
- [Clean-history upstream update workflow](docs/soorin/upstream-sync.md)
- [Sprint 1 architecture audit](docs/soorin/SPRINT1_ARCHITECTURE_AUDIT.md)
- [Utopia capability matrix](docs/soorin/UTOPIA_CAPABILITY_MATRIX.md)
- [SOC foundation gap analysis](docs/soorin/SOC_FOUNDATION_GAP_ANALYSIS.md)
- [Agentic SOC data-contract analysis](docs/soorin/AGENTIC_SOC_DATA_CONTRACT_ANALYSIS.md)
- [Agentic SOC `llm_payload` field mapping](docs/soorin/LLM_PAYLOAD_FIELD_MAPPING.md)
- [Future agent compatibility](docs/soorin/FUTURE_AGENT_COMPATIBILITY.md)
- [SOC knowledge architecture](docs/soorin/SOC_KNOWLEDGE_ARCHITECTURE.md)
- [SOC ontology](docs/soorin/SOC_ONTOLOGY.md)
- [Entity resolution](docs/soorin/ENTITY_RESOLUTION.md)
- [Temporal model](docs/soorin/TEMPORAL_MODEL.md)
- [Model configuration](docs/soorin/MODEL_CONFIGURATION.md)
- [Retrieval and reranking](docs/soorin/RETRIEVAL_AND_RERANKING.md)
- [Local development](docs/soorin/LOCAL_DEVELOPMENT.md)
- [Testing and evaluation](docs/soorin/TESTING_AND_EVALUATION.md)
- [Sprint 1 implementation report](docs/soorin/SPRINT1_IMPLEMENTATION_REPORT.md)
- [Utopia upstream README](README.upstream.md)

## Security and attribution

Fixtures are **entirely synthetic**; no production SIEM events, credentials, source tokens, or personal identifiers belong in this public repository. Local `.env`, `data/`, DB contents, session cookies, and `secret.key` must not be committed. The original Utopia code remains under the bundled Apache-2.0 `LICENSE`; preserve upstream copyright and notices. A clean commit history does **not** remove licensing obligations.

Rust crate names, package identifiers, binary names, Docker image, and existing upstream documents still refer to Utopia until intentionally rebranded and rebuilt. Avoid mass-renaming a working baseline.
