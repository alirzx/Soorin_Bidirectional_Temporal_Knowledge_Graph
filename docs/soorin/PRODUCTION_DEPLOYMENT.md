# Independent Soorin deployment

Status: configuration prepared and statically validated. No image built, release
published, stack started, or production acceptance claimed in this pass.

Use `docker-compose.production.yml`, optionally with
`docker-compose.models-production.yml`.
The optional `models` profile now runs **one** CPU-only container with a
qualified image and three verified, read-only cache volumes. Its internal
listeners are `models:8080` (embedding), `models:8081` (reranker) and
`models:8082` (review-only NER); none are published to host. Set
`UTOPIA_MODEL_TRUSTED_ORIGINS` to the three corresponding `http://models`
origins, and update workspace settings to the exact same internal model URLs.
The three models must ALL be present at immutable pinned revisions: the
container fails startup if even one is absent. Provision 7 GiB max memory and
3 CPUs in the current template; benchmark real peak memory and latency before
production, as all models share a fate and one inference semaphore.
 The generic `docker-compose.yml` defaults
to an upstream Utopia image and must not be used as the Soorin production path.

1. Qualify the exact feature commit using [Build and test handoff](BUILD_AND_TEST_HANDOFF.md).
2. Build/sign/scan and publish a Soorin image through the reviewed release process.
   This repository does not claim a published production image exists. Set
   `SOORIN_IMAGE` to its immutable digest, and select reviewed PostgreSQL/model
   image digests. The application Dockerfile uses Rust 1.99.1 on Bookworm, a
   Bookworm runtime, Cargo lockfile, and frozen pnpm lockfile. Node/Python/OS
   base tags and Python transitive packages still need release supply-chain review.
3. Copy `soorin/config/production.env.example` to an operator-owned mode-0600 file
   outside Git. Replace every placeholder. Prefer a deployment secret manager;
   environment injection is supported but visible to Docker administrators.
4. Create independent runtime, migration and backup identities. For a fresh DB,
   the init hook creates `utopia_app` before migrations. For an existing DB it
   does not run: provision the role as DBA and reproduce migration 0010 grants
   under the actual owner, including append-only audit restrictions, before
   switching credentials. Never edit or replay an applied migration just to grant
   privileges. Migration 10003 removes runtime access to SQLx's ledger.
5. Back up PostgreSQL, `/app/data` and the encryption key together. Test restore
   on a separate instance. Existing data volumes must be owned/writable by UID
   65532 before adopting the non-root image; never recursively change unrelated
   host paths or start a privileged app to hide a permission error.
6. Statically validate the explicit production files:

```bash
timeout 15s docker compose --env-file /secure/soorin-production.env \
  -p soorin-production -f docker-compose.production.yml config --quiet
# Include the model overlay only when its image/caches have been qualified.
timeout 15s docker compose --env-file /secure/soorin-production.env \
  -p soorin-production -f docker-compose.production.yml \
  -f docker-compose.models-production.yml config --quiet
```

7. In the separately approved deployment window, start DB/app, verify migration
   checksums, runtime DB role, API and UI, then bootstrap the first administrator
   while the API is private. `OPEN_REGISTRATION=false` still permits the first
   account by design; do not expose that bootstrap window publicly.
8. Configure a host TLS proxy from the exact `SOORIN_PUBLIC_ORIGIN` to
   `127.0.0.1:2516`, preserve streaming, limit body size/timeouts, and set
   `X-Forwarded-Proto: https`. There is no built-in public TLS listener. CORS is
   deployment-owned and exact; production must not use the development origin.
9. Configure workspace models and the trusted privacy tenant map separately.
   Starting a profile does not configure workspace settings. Do not add raw
   external providers to trusted internal origins.

No database or model port is published in production. App/model containers drop
capabilities, use read-only roots and bounded tmpfs/PIDs/memory/CPU. The app data
volume and DB data are persistent. Postgres keeps its standard initialization
privileges; it is not falsely described as a read-only non-root container.
The app is attached to an egress network: enforce destination policy in the
host/network infrastructure as well as application policy.

## Health, observability and rollback

`/api/v1/health` means the API is responding; it is not proof of model availability,
typed graph completion, queue health, privacy readiness or database restore safety.
Model `/ready` is load readiness, not an inference quality test. `/v1/models`
reports the pinned model identity. Inspect source receipt status/failure code,
job attempts/age, identity conflict counts, typed relations, context truncation,
embedding backfill, reranker fallback and gateway failure rates separately.
Use IDs/counts/status codes; never export raw receipt payloads, prompts, credentials,
provider bodies or decoded aliases into telemetry. Broad legacy pipeline error
logging needs content review before exporting logs to an external system.

CI's release workflow verifies the latest CI run for the exact commit and uses
`production-release` environment gates. Configure required reviewers and branch
protection in both repositories. Do not tag/publish from this engineering session.

Rollback is image/config rollback against a compatibility-tested schema. Migrations
are roll-forward; no downgrade SQL or volume deletion is provided. For incompatible
schema changes, restore the tested pre-upgrade backup into a separate database
and restore matching data/key material, then switch traffic under incident control.
Do not blindly run an older binary against a newer schema.

## V1 baseline update

V1 baseline parameterizes app publication as `SOORIN_APP_BIND` (default 127.0.0.1:2516); use a verified unused bind before deployment. Keep DB/model ports internal. Future Agentic access requires approved DNS/TLS reverse proxy, narrowly scoped read PAT and separate TKG Privacy Gateway client authorization; no running server network was joined. Local QA uses [the dedicated project/env](LOCAL_DEVELOPMENT.md), not this production template. No immutable image qualification, backup restore or live gateway test occurred in this pass.
