# Local development

## Preserve the verified rc9 service

The existing service is `http://127.0.0.1:1516`, database host port `1517`, prebuilt image `ghcr.io/deeplethe/utopia:0.1.0-rc9`, and contains `Soorin SOC Lab`. Source edits do not appear in that container. Do not stop it, reuse its volume, run `docker compose down -v`, or run destructive graph rebuilds.

Read-only checks:

```bash
docker compose -f docker-compose.local.yml --profile app ps
curl -fsS http://127.0.0.1:1516/api/v1/health
```

## Offline Python foundation

Python 3.12 is used in CI. The runtime modules are mostly standard-library; schema tests add the small test-only dependency set below. CPU NER dependencies are separate and are not needed for the foundation suite.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r soorin/requirements-test.txt
python -m compileall -q soorin
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
```

## Isolated source build

`docker-compose.soorin-dev.yml` builds `docker/Dockerfile`, uses independent named volumes, and binds app/database to 2516/2517. It does not mount `./data`.

Prerequisites are Docker Engine with Compose v2, enough disk for the Rust/Node build cache and images, and free loopback ports 2516/2517. The multi-stage image builds the React UI with the lockfile-pinned pnpm version and the Rust API on Debian Bookworm, then installs only the runtime binary, UI, Poppler, CA certificates, and `curl`. It does **not** run the Python Soorin package or optional NER as a service.

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml config --quiet
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml up -d --build
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml ps
curl -fsS http://127.0.0.1:2516/api/v1/health
```

The app waits for PostgreSQL health, runs embedded SQLx migrations at startup, and has its own API healthcheck. Review migration/app logs before creating the first account:

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml logs --tail=200 db app
```

The default development database password is acceptable only on the loopback-only isolated stack. Set a random `SOORIN_DEV_DB_PASSWORD` for any shared machine. Registration is closed after the first bootstrap account; do not publish 2516/2517 or relax the bind addresses.

Use only an isolated test KB in this stack. To stop it without deleting test data:

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml down
```

Deleting its independent volumes is a separate destructive operation and is not part of normal testing.

If memory is constrained, leave Chat, embedding, reranking, and CPU NER disabled for initial startup and lower worker concurrency through the authenticated deployment settings after boot. Do not run local model servers alongside the source build until baseline API/database resource use is measured.

## Native backend/frontend

Read the repository toolchain before running. Backend uses Cargo workspace commands. Frontend declares `pnpm@10.2.1` in `web/package.json` and supports `pnpm test`, `pnpm typecheck`, and `pnpm build`. Database-dependent Rust tests require PostgreSQL/pgvector and must not target the existing lab database.

Graphify artifacts remain local in `graphify-out/`; open `graphify-out/graph.html` directly in a browser for the aggregated code graph.

The exact pre-build and next-phase PostgreSQL/Cargo commands are recorded in [Pre-build validation](PREBUILD_VALIDATION.md).

## Makefile: isolated low-memory source build (2026-11-02)

The root `Makefile` is a convenience wrapper over `docker-compose.soorin-dev.yml`.
It never points to the legacy rc9 database. The old `utopia_dbdata` volume must
be preserved unless an explicit, separately reviewed backup/deletion decision is made.

**One-time setup:**

```bash
make env-init                        # writes .env with a random 48-char hex DB password
make old-inspect                     # inspect exactly two legacy containers
make old-remove                      # removes only STOPPED utopia-app-1/utopia-db-1
make image-remove                    # removes rc9 image if no container references it
make preflight                       # validate Compose, ports and host resources
```

If `.env` already exists, `env-init` fails rather than overwriting its
database password. The committed template is `soorin/config/sprint1.compose.env.example`.
`SOORIN_BUILD_JOBS=1` limits Rust release build concurrency; the app also
defaults to `SOORIN_DEV_DB_MAX_CONNECTIONS=8`. Both are development tuning, not
model settings. Watch host RAM and swap because other Docker services share them.

**Build from source and run:**

```bash
make build                           # cached frontend + Rust release + runtime image
make up                              # PostgreSQL 16/pgvector + app/API/UI/workers
make ps
make health                          # API + embedded React frontend
make migrations                      # check migrations 0111 and 0112
make logs                            # investigate startup or worker failures
```

Use `make build-fresh` only when a cache-free rebuild is necessary; it does
**not** remove Docker volumes. Never use `docker system prune --volumes`
as part of routine development. The old `utopia_dbdata` volume and the separate
`soorin-sprint1` named volumes are not cleanup targets.

**Foundation and models:**

```bash
make offline
make mock-check
make e2e-offline
# After creating a fresh 2516 KB/source and exporting required credentials:
make e2e-live E2E_EXECUTE=YES
```

The Python SDK and optional CPU NER are not deployed inside the Rust app image.
Create an isolated Python virtual environment before running `make ner-install`;
`make ner-smoke` requires pre-reviewed model weights already in the local HF cache.
Chat and Embedding for the active Rust pipeline are configured through authenticated
Utopia Workspace Settings, not through the Python-only `SOORIN_CHAT_*` variables.

**Important:** `make old-remove` deliberately refuses to remove *running*
legacy containers and `make image-remove` refuses removal while any container
references the old rc9 image. They do not delete volumes. E2E live tests
require explicit credentials and run only against `127.0.0.1:2516`.
