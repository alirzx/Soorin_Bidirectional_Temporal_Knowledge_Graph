# Controlled build and integration handoff

Run this plan only in the next approved build/runtime window. The engineering
pass did not execute heavy builds, database migrations, service startup or model
inference. Never target an existing lab/production DB or reuse its data volume.
Record exact Git/image hashes, toolchain, hardware, sanitized commands, durations,
exit codes and report paths. A timeout is BLOCKED, not PASS; do not loop slow jobs.

## Phase A — Rust and frontend

Use Rust 1.99.1 (the formatter/metadata version used in this pass), installed
rustfmt/clippy, locked dependencies and a qualified disposable PostgreSQL URL.
First inspect git status and capture the SHA. Commands below are stage budgets,
not permissions to run them during the current lightweight session.

```bash
timeout 20s cargo fmt --all --check
timeout 30s cargo metadata --locked --offline --no-deps --format-version 1
timeout 600s cargo check --locked --workspace --all-targets
timeout 600s cargo clippy --locked --workspace --all-targets -- -D warnings
# Set UTOPIA_DATABASE_URL to an isolated, already migrated test database.
UTOPIA_MODEL_TEST_MODE=1 UTOPIA_TEST_REQUIRE_DB=1 timeout 900s cargo test --locked --workspace
CARGO_BUILD_JOBS=1 timeout 1800s cargo build --locked --release --workspace
```

Never reuse the old target logs as proof for a new commit. Rust tests include
source/checksum validation, storage policy, asserted confidence, context bounds,
identity races, model cache reuse and gateway fault/cancellation behavior. Ensure
DB tests actually run; record every skip. Install Poppler for PDF tests during
controlled setup, not an unbounded test fallback. Model mocks must remain active.
Frontend from `web/`: `timeout 60s pnpm test`, `timeout 60s pnpm typecheck`,
`timeout 120s pnpm build`, using preinstalled locked dependencies.

## Phase B — PostgreSQL

Provision two **empty disposable databases** on a test server, then export the
appropriate URL for each command. Never set these to a lab DB containing user data.

```bash
UTOPIA_DATABASE_URL="$SOORIN_FRESH_TEST_URL" timeout 300s cargo run --locked -p utopia-store --example migrate
UTOPIA_DATABASE_URL="$SOORIN_FRESH_TEST_URL" timeout 300s cargo run --locked -p utopia-store --example migrate
UTOPIA_DATABASE_URL="$SOORIN_UPGRADE_TEST_URL" timeout 300s cargo run --locked -p utopia-store --example verify_soorin_upgrade
```

The upgrade utility refuses initialized databases, builds the <=0112 schema,
seeds synthetic content, applies the current schema twice and checks preserved
content/checksums. Current tree contains 104 migrations, latest 10003. Also test
upgrade from a sanitized clone of the real deployment: 0111/0112/10001/10002 must
keep exact checksum bytes, 10002 legacy evidence stays NULL, new links get actual
attachment time, 10003 listing index exists and `utopia_app` cannot edit
`_sqlx_migrations`. Exercise runtime permissions after granting under the actual
migration owner; verify audit rows cannot be updated/deleted.

Export `version, encode(checksum,'hex') AS checksum_hex` from SQLx's migration
ledger as a JSON array and run `python3 -m soorin.ops.migrations --applied-json FILE`.
The local upstream comparison intentionally fails on 0111; do not merge upstream.
See [reconciliation](upstream-sync.md).

## Phase C — Docker / application

Prepare an isolated project/ports with no collision. The source-development file
defaults to occupied 2516/2517; override through soorin/config/qa.env.example to 2526/2527 after inventory. Build once with
an explicit deadline and job limit; save the output, do not repeatedly restart it.

```bash
SOORIN_BUILD_JOBS=1 timeout 1800s docker compose --env-file soorin/config/qa.env.example -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml build app
```

For production-image qualification, validate the explicit production file with
operator-owned env values and an immutable Soorin image. Start only after an
approved environment inventory. Check UID 65532 data writes, DB role separation,
health, UI login/bootstrap, restart persistence, CORS/TLS proxy, secret injection
and backups. App startup must work with all optional model profiles absent.
Never use `down -v`, pruning or an old lab source as test cleanup.

## Phase D — model runtime (separately approved)

1. Inspect caches and verify manifest/revision/hash using
   [Artifact management](MODEL_ARTIFACT_MANAGEMENT.md). Preserve partial downloads.
2. Build/qualify the CPU image separately. Current source includes lifecycle fixes
   absent from earlier cached images. No large image pull is implicit in this plan.
3. Load one model at a time, offline/read-only/non-root, with memory/CPU/PID limits.
4. On a private test endpoint, run `python3 -m soorin.ops.models smoke --role ROLE
   --base-url URL` under a 60-second timeout. This command **does inference**.
5. Validate BGE 1024 finite vectors, stable repeated text, multilingual probes;
   reranker all candidate indices and finite scores; NER review-only proposals,
   English scope and unsupported-script behavior. Never infer security accuracy
   from service readiness or synthetic shape tests.
6. Record startup/warm memory, CPU, latency p50/p95, cache restart and timeout
   behavior. Do not simultaneously load all models on a constrained host.
7. Configure workspace embedding fingerprint and run explicit backfill. Confirm
   old/unknown model vectors are excluded and failed jobs are visible.

## Phase E — synthetic SOC and privacy

The native harness is opt-in and verifies the new QA project/volumes at loopback
2526; it refuses existing labs and creates only synthetic accounts/KBs/sources.

```bash
SOORIN_DISPOSABLE_ACCEPTANCE=1 timeout 300s python3 -m soorin.e2e.native_validation \
  --base-url http://127.0.0.1:2526 --qa-project soorin-tkg-v1-qa --approved-port 2526 \
  --execute --deadline 120 \
  --report /tmp/soorin-native-acceptance.json
```

The harness alone is not complete release acceptance. Supplement it with explicit
cases: concurrent duplicate delivery, identity conflict, crash at registered and
submitted transitions, lease expiration, failed-job retry authorization, late/equal
source-clock quarantine, human-rejected binding preservation, recognized typed
relations before bound, duplicate-free context, two-tenant isolation, evidence
attached after `as_of`, document delete/restore, and response truncation. Verify
new admission/minimization behavior with the real producer's curated schema.

Run existing gateway mock tests first. Then, with synthetic content and approved
credentials, validate canonical workspace→privacy tenant mapping, context ownership,
encode/decode shape, unknown aliases, cancellation/TTL cleanup, no redirect/raw
provider fallback and no secrets in logs. Real DeepSeek tools/streaming behavior
and private reasoning continuation require a separate authorized provider test.
Agentic_SOC integration remains read-only; no live Agentic mutations are included.

Offline retrieval baseline command:
`timeout 15s python3 -m soorin.evaluation.retrieval_benchmark`.
It reports Recall@K/MRR/nDCG/p50/p95 for four synthetic documents and three queries,
using fake vectors/reranking. Native production ranking requires a separate,
versioned bilingual relevance set, temporal split, tenant-isolation cases, lexical
baseline, dense/RRF/reranker ablations, hardware/config pins and saved failures.
No quality improvement is claimed from the tiny smoke corpus.

Release remains blocked until all required gates pass on the exact image and
operators approve the deployment/rollback evidence. This handoff does not merge
main, publish an image, or grant production release approval.
