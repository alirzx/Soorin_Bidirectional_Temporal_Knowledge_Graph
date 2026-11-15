# Pre-build validation

This phase is lightweight and model-free. Full build/runtime commands are in
[Build and test handoff](BUILD_AND_TEST_HANDOFF.md), with observed results in
[Final acceptance](FINAL_ACCEPTANCE_REPORT.md).

```bash
timeout 20s cargo fmt --all --check
timeout 30s cargo metadata --locked --offline --no-deps --format-version 1
PYTHONDONTWRITEBYTECODE=1 python3 -c "import ast,pathlib; [ast.parse(p.read_text(),filename=str(p)) for p in pathlib.Path('soorin').rglob('*.py')]"
PYTHONDONTWRITEBYTECODE=1 timeout 60s python3 -m unittest discover -s soorin/tests -p 'test_*.py'
timeout 15s python3 -m unittest discover -s soorin/tests/mock_splunk/tests
timeout 15s docker compose -f docker-compose.soorin-dev.yml -f docker-compose.models.yml config --quiet
timeout 15s docker compose --env-file soorin/config/production.env.example -f docker-compose.production.yml config --quiet
timeout 15s docker compose --env-file soorin/config/production.env.example -f docker-compose.production.yml -f docker-compose.models-production.yml config --quiet
git diff --check
```

Python tests use injected model objects/transports and synthetic fixtures, never
real weights. Do not run `serve`, model `smoke`, external provider tests, backfill,
image builds or the full Rust suite in this phase. Existing caches are inspected
with `verify-artifacts`, not initialization/loading. Production example values
are placeholders: successful Compose parsing is not a usable deployment.

For the 2026-11-15 continuation, local Rust compilation, frontend builds,
dependency installation/download, Docker startup, migration execution, model
loading and live E2E are prohibited. Run only installed formatters, AST/JSON/shell
checks, `docker compose config --quiet`, and bounded mock-only Python tests.
No usable native rustfmt is currently installed on this host; the cached binary
lacks its rustc driver library. Do not start a formatter container or install a
toolchain to work around that restriction. Automatic GitHub CI provides Rust
format/lint/build/test evidence; inspect the exact final SHA. Historical reports
are not proof for current HEAD. See [Continuation report](CONTINUATION_HARDENING_REPORT.md).
