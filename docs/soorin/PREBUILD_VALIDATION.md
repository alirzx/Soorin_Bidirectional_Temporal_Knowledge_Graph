# Pre-build validation gates

This checklist separates lightweight static checks from the next local source-build phase. Never point database tests at the existing `Soorin SOC Lab` or reuse its volumes.

## Lightweight checks

```bash
python3 -m compileall -q soorin
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
python3 -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
python3 -m soorin.e2e.local_validation --report /tmp/soorin-e2e-offline.json
docker compose -f docker-compose.soorin-dev.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.build.yml --profile app config --quiet
git diff --check
```

Frontend checks, when the lockfile dependencies are already installed:

```bash
cd web
pnpm test
pnpm build
```

## Rust and PostgreSQL gate

Use a disposable PostgreSQL 16 + pgvector database. These commands are required before merge; unavailable tools are `NOT RUN`, never a pass.

```bash
cargo fmt --all -- --check
cargo check --workspace --all-targets
export UTOPIA_DATABASE_URL='postgres://utopia:utopia@127.0.0.1:2517/utopia'
export UTOPIA_TEST_REQUIRE_DB=1
cargo run -p utopia-store --example migrate
cargo test --workspace
```

Migration acceptance requires a fresh database, a second no-op migration run, registry concurrency/cross-KB tests, and inspection of migration `0112`. Do not alter an applied migration checksum.

## Source-build and isolated E2E gate

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml up -d --build
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml ps
curl -fsS http://127.0.0.1:2516/api/v1/health
```

After boot, use only a new isolated KB and the synthetic E2E harness. Confirm migration completion, ontology preview/apply, Statements replay, background jobs, typed graph assertions, `at`/`as_of`, exact/BM25 search, and semantic search only when Workspace Settings embeddings are genuinely configured. Stop without deleting data:

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml down
```

Volume deletion is a separate destructive cleanup decision and is never part of routine validation.
