# Soorin Bidirectional Temporal Knowledge Graph

An independent Soorin engineering repository for temporal security knowledge, provenance-aware graph retrieval, and eventual integration with Agentic SOC. The initial implementation is based on **Utopia v0.1.0-rc9**, with a new Soorin root commit and a separately maintained upstream remote.

## Local status and scope

- Baseline: Rust Utopia server, PostgreSQL + pgvector, embedded Tantivy index, React UI.
- Local deployment: `docker compose -f docker-compose.local.yml --profile app up -d`.
- Health: `curl -fsS http://127.0.0.1:1516/api/v1/health`.
- Lab knowledge base: **Soorin SOC Lab** (create/select this in the UI; it is database state, not Git data).
- First integration: synthetic Splunk ES notables, fused alerts, Windows Security events, SOC case, and Jira ticket.
- **Not yet delivered:** production Splunk connector, typed SOC ontology, deterministic tenant-aware entity resolution, guaranteed graph availability, or live Agentic SOC integration.

## First SOC ingestion test

See [the mock lab guide](soorin/tests/mock_splunk/README.md) and [the local smoke checklist](docs/soorin/local-smoke.md).

```bash
python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
# After creating a Statements source in the Soorin SOC Lab KB:
export UTOPIA_SOURCE_ID='<source-uuid>'
read -rsp 'Utopia source token: ' UTOPIA_INGEST_TOKEN; echo
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
- [Utopia upstream README](README.upstream.md)

## Security and attribution

Fixtures are **entirely synthetic**; no production SIEM events, credentials, source tokens, or personal identifiers belong in this public repository. Local `.env`, `data/`, DB contents, session cookies, and `secret.key` must not be committed. The original Utopia code remains under the bundled Apache-2.0 `LICENSE`; preserve upstream copyright and notices. A clean commit history does **not** remove licensing obligations.

Rust crate names, package identifiers, binary names, Docker image, and existing upstream documents still refer to Utopia until intentionally rebranded and rebuilt. Avoid mass-renaming a working baseline.
