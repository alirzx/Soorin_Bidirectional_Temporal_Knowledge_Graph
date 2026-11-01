# Local development

## Preserve the verified rc9 service

The existing service is `http://127.0.0.1:1516`, database host port `1517`, prebuilt image `ghcr.io/deeplethe/utopia:0.1.0-rc9`, and contains `Soorin SOC Lab`. Source edits do not appear in that container. Do not stop it, reuse its volume, run `docker compose down -v`, or run destructive graph rebuilds.

Read-only checks:

```bash
docker compose -f docker-compose.local.yml --profile app ps
curl -fsS http://127.0.0.1:1516/api/v1/health
```

## Offline Python foundation

No virtual environment or third-party package is required:

```bash
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
```

## Isolated source build

`docker-compose.soorin-dev.yml` builds `docker/Dockerfile`, uses independent named volumes, and binds app/database to 2516/2517. It does not mount `./data`.

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml config --quiet
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml up -d --build
curl -fsS http://127.0.0.1:2516/api/v1/health
```

Use only an isolated test KB in this stack. To stop it without deleting test data:

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml down
```

Deleting its independent volumes is a separate destructive operation and is not part of normal testing.

## Native backend/frontend

Read the repository toolchain before running. Backend uses Cargo workspace commands. Frontend declares `pnpm@10.2.1` in `web/package.json` and supports `pnpm test`, `pnpm typecheck`, and `pnpm build`. Database-dependent Rust tests require PostgreSQL/pgvector and must not target the existing lab database.

Graphify artifacts remain local in `graphify-out/`; open `graphify-out/graph.html` directly in a browser for the aggregated code graph.
