# Pre-build validation

This phase is lightweight and model-free. Full build/runtime commands are in
[Build and test handoff](BUILD_AND_TEST_HANDOFF.md), with observed results in
[Final acceptance](FINAL_ACCEPTANCE_REPORT.md).

```bash
timeout 20s cargo fmt --all --check
timeout 30s cargo metadata --locked --offline --no-deps --format-version 1
timeout 30s python3 -m compileall -q soorin
timeout 45s python3 -m unittest discover -s soorin/tests -p 'test_*.py'
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

Focused branch review also runs the existing frontend typecheck/test/guard scripts
with already-installed dependencies. A short frontend asset build is allowed;
a full application/Rust/image build is not implied. In an environment without pnpm,
invoke the corresponding installed `tsc`, `vitest`, style-guard and Vite executables
directly. Affected Rust tests may run once with a bounded offline compilation
budget; a timeout is NOT RUN, not a reason to restart compilation repeatedly.
Integration requires verified exact-commit CI; preserve the hardening branch if
that gate is unavailable. See [Pre-build report](PREBUILD_HARDENING_REPORT.md).
