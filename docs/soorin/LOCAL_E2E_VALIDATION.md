# Isolated local E2E validation

`soorin.e2e.local_validation` is the acceptance harness for the first source
build. It uses only the synthetic fixture
`soorin/tests/fixtures/soc_e2e_scenarios_v1.json`. The default invocation is
offline and cannot write to Utopia:

```bash
python3 -m soorin.e2e.local_validation \
  --report /tmp/soorin-e2e-offline.json
```

The report schema is `soorin.soc.e2e-report.v1`. Every check is recorded as
`PASS`, `FAIL`, `SKIPPED`, `BLOCKED`, or `NOT RUN`; a missing graph job or model
is never converted into a success.

## Safety boundary

Live mode accepts only `http://127.0.0.1:2516`, `localhost:2516`, or the IPv6
loopback equivalent. Port `1516` is rejected unconditionally because it belongs
to the existing Utopia/SOC lab. Public hosts, HTTPS endpoints, URL credentials,
paths, query strings, and alternate ports are also rejected. The live fixture
pushes only `tenant-blue` rows. The other-tenant record is an offline identity
isolation assertion and is not written to the selected knowledge base.

Create a new Statements source inside the isolated `2516/2517` deployment and
obtain its ingest token. Obtain a short-lived Utopia session JWT for a user with
viewer access to the selected KB. Keep both values in the shell; the harness
does not print them or include provider response bodies in errors.

```bash
export UTOPIA_BASE_URL=http://127.0.0.1:2516
export UTOPIA_KB_ID=<isolated-kb-uuid>
export UTOPIA_SOURCE_ID=<isolated-statements-source-uuid>
export UTOPIA_INGEST_TOKEN=<source-ingest-token>
export UTOPIA_SESSION_TOKEN=<session-jwt>

python3 -m soorin.e2e.local_validation \
  --execute \
  --report /tmp/soorin-e2e-live.json
```

Use `--semantic-enabled` only after Workspace Settings has a working embedding
provider. Utopia's search endpoint returns fused chunks but does not expose
per-channel attribution, so the report explicitly records that limitation.

## Covered acceptance cases

The fixture and offline checks cover initial ingestion, exact replay, status
change, corrected source-event references, late arrival, multiple source events,
multiple evidence references, a host shared by alerts, a hostname repeated
across tenants, a private IP repeated across network scopes, and Case/Ticket
relationships. The live phase pushes the isolated-tenant rows in revision order,
requires the immediate exact replay to return `unchanged`, polls graph/job state,
fetches actual graph data, checks expected ontology types and relationships, and
runs historical, identifier, and BM25 queries.

Persistent identity-conflict execution remains `BLOCKED` in this harness because
the registry is deliberately dormant in Foundation ingestion. Its cross-KB,
concurrency, alias-history, and compare-and-set behavior must be verified by the
migration-backed Rust tests before Sprint 2 activation.

## Interpreting results

- `PASS`: observed locally by this run.
- `FAIL`: an executed assertion was false or an executed operation failed.
- `SKIPPED`: an optional prerequisite such as embeddings was not declared.
- `BLOCKED`: the current runtime surface cannot prove the condition.
- `NOT RUN`: live execution was not requested.

Stop the isolated Compose project without deleting data:

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml down
```

Do not add `--volumes`; the E2E runbook never requires a database reset.
