# Soorin SOC Lab: local smoke runbook

> Historical checkpoint. Current behavior and evidence are in [Final acceptance](FINAL_ACCEPTANCE_REPORT.md) and [Production architecture](PRODUCTION_ARCHITECTURE.md).

## Prerequisites and deployed baseline

Run commands from the repository root. The baseline uses Docker Compose, the upstream `ghcr.io/deeplethe/utopia:0.1.0-rc9` image, PostgreSQL 16 and port 1516 on loopback. This project's local Compose file has an older default image tag, so explicitly set `UTOPIA_IMAGE` in your ignored local `.env`.

```bash
cd /mnt/X/Soorin/soorin_bi_TKG/utopia
export UTOPIA_IMAGE='ghcr.io/deeplethe/utopia:0.1.0-rc9'
docker compose -f docker-compose.local.yml --profile app config --quiet
docker compose -f docker-compose.local.yml --profile app ps
# Only start the stack if it is not already running and configuration/volumes have been verified:
# docker compose -f docker-compose.local.yml --profile app up -d
docker compose -f docker-compose.local.yml --profile app ps
curl -fsS http://127.0.0.1:1516/api/v1/health
```

Do not run `docker compose down -v`; it deletes the PostgreSQL volume holding your account and `Soorin SOC Lab` knowledge base.

## Dataset validation (offline, no credentials needed)

```bash
python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 soorin/tests/mock_splunk/scripts/soc_mock.py render --output-dir /tmp/soorin-soc-statements
```

## Ingest into Soorin SOC Lab

1. Open `http://127.0.0.1:1516` and select **Soorin SOC Lab**.
2. In Library, create a Source of type **Statements** named `Splunk SOC Synthetic Lab`.
3. Copy its UUID and **ingest token** from source settings. Do not copy the UI session cookie, PAT, or password into the source token variable.
4. Run:

```bash
export UTOPIA_BASE_URL='http://127.0.0.1:1516'
export UTOPIA_SOURCE_ID='<actual-statements-source-uuid>'
# Zsh syntax (Bash uses: read -rsp 'Enter source ingest token: ' UTOPIA_INGEST_TOKEN)
read -rs 'UTOPIA_INGEST_TOKEN?Enter source ingest token: '; echo
export UTOPIA_INGEST_TOKEN
python3 soorin/tests/mock_splunk/scripts/soc_mock.py push
python3 soorin/tests/mock_splunk/scripts/soc_mock.py push --replay
unset UTOPIA_INGEST_TOKEN
```

The Compose files default to upstream rc8; the earlier verified lab used rc9. The commands above set `UTOPIA_IMAGE` for the current shell session without editing `.env`. An existing ignored local `.env` may also override it; inspect the resolved Compose configuration before starting or changing containers.
Source changes are not present in that prebuilt container. For an isolated
source build, use the build override described in `LOCAL_DEVELOPMENT.md`; do
not replace the existing volume or run `down -v`.

First push should report `created` for nine IDs. An identical replay should report `unchanged`. If you already pushed them, the first observed action may be `unchanged`. Any non-2xx response is a failure and prints a bounded error body. The Python sender uses only standard-library HTTPS/HTTP libraries and does not log source tokens.

## Graph verification (a distinct acceptance gate)

Check Library for 9 documents, inspect `graph_status` and graph-processing errors, then open `/kb/<KB_UUID>/graph`. Search `SPLUNK-NOTABLE-001`, `dc-auth-01.corp.example`, `SOC-CASE-001`, and `SOC-101`.

Authenticated graph endpoint:
`GET /api/v1/kbs/{kb_id}/graph/overview?limit=150`. You can inspect its response via your browser's authenticated session. It returns `nodes`, `edges`, `total_nodes`, `total_edges`. **Do not** confuse ingested document count with graph node count.

Review unaligned phrases/kinds under Ontology / Review. A source push bypasses **LLM extraction**, not alignment or other model-dependent graph work. Check model configuration and worker queue before reporting an empty graph as an ingestion failure.

## Diagnostics

```bash
docker compose -f docker-compose.local.yml --profile app logs --tail=150 app
docker compose -f docker-compose.local.yml --profile app logs --tail=80 db
docker compose -f docker-compose.local.yml --profile app ps
```

If the database is healthy and the API returns `ok` but the typed graph is empty, inspect document `graph_status`, job errors, missing alignment model, ontology mappings, and source type first.

## Security and resource notes

- Current lab is loopback-only; PostgreSQL default password and open registration are **not** production defaults.
- The current DB role warning `utopia_app role does not exist` is nonfatal locally; least-privilege runtime credentials are needed before production.
- Back up PostgreSQL plus `./data` (including `secret.key`) together; Git contains neither.
- On 15 GiB RAM workstations, avoid piling on simultaneous local LLMs before measuring the worker's memory use.
