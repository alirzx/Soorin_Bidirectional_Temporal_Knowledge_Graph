# Local and Server 55 source deployment

Run `scripts/source_deploy.py` from a clean, approved checkout. Use Python 3.11+,
Docker with BuildKit and Compose v2.24.4+ (including the override/reset tags).
Use one operator and one Docker context throughout the maintenance window.
The immutable registry deployment retains its own digest validator and command.
[Immutable deployment](SERVER55_PRODUCTION_RELEASE.md#canonical-hardened-production-interface)

## Topology and configuration

| Service | Connections and state | Default cap |
|---|---|---|
| db | PG16 with pgvector on private database network, named PGDATA volume, existing first-init role hook | 2 CPUs / 2 GiB |
| app | Runtime login utopia_app, migration owner utopia, named /app/data, loopback HTTPS proxy or explicit private LAN HTTP | 2 CPUs / 2 GiB |
| models-proxy | Internal DNS alias models on the app's models network, forwards to the private worker network | 0.15 CPU / 128 MiB |
| models-embedding | Offline BAAI/bge-m3 on port 8080 through proxy, read-only /models/embedding | 1.2 CPUs / 3 GiB |
| models-reranker | Offline BAAI/bge-reranker-v2-m3 on port 8081 through proxy, read-only /models/reranker | 1.4 CPUs / 3 GiB |

Allow host, build, page-cache and backup headroom above the combined runtime limits.
Measure concurrency, RSS, cold-start time and queue deadlines on the target.
Both workers run as UID 65532 using one CPU-only image. Configure workspace model
identities using the pinned revisions in `soorin/services/cpu_models.py`. The app trusts
`http://models:8080` and `http://models:8081`. Ordinary serving verifies local
artifacts with hashes. The app, proxy, and workers use read-only root filesystems.

Initialize the ignored file **once** in each checkout. Preserve an existing file.
Set private entries using the host's approved secret-handling procedure.

```bash
test -e .env || install -m 0600 .env.example .env
chmod 0600 .env
```

[The environment template](../../.env.example) includes project and lifecycle, explicit database and app-data volumes, cache names, access mode, exact browser origin and app binding, pool size, separate owner/runtime passwords and URLs, signing and encryption keys, image references, BuildKit inputs and mirrors, per-role budgets, optional diagnostics, SOC and DLP. Use `postgres://utopia_app:<encoded-runtime-password>@db:5432/utopia` and `postgres://utopia:<encoded-owner-password>@db:5432/utopia`. Supply a high-entropy signing secret and a 32-byte encryption key. The runner stamps both images with the full checkout SHA. Stage approved DB and nginx digest references locally before cutover. Keep build concurrency at one for a constrained builder.

Choose one project for the whole lifecycle. These commands render and validate actual
Compose inputs and print the project, lifecycle and service names. Direct Compose
config output includes resolved credentials. Clear stale exported deployment variables
before invoking the runner (shell values take precedence over dotenv).

```bash
scripts/source_deploy.py config --project soorin-tkg-local
scripts/source_deploy.py config --project soorin-tkg-server55
```

The runner orders the production base, isolated workers and source overrides, then
the optional LAN HTTP, SOC, diagnostic and NER overlays. Legacy Makefile QA targets use their
original development Compose and profiles. Source builds use the following stages
on a qualified build host. Set `project` to the appropriate name above.

```bash
project=soorin-tkg-local
# On Server 55 use project=soorin-tkg-server55, or its inventory-confirmed project name.
run() { scripts/source_deploy.py "$@" --project "$project"; }
run config
run build-app
run build-models
run images
```

The two builds are independent. Building the embedding service produces the
shared CPU image. The app label must match HEAD. The model label must match the selected full
model revision (defaults to HEAD). To reuse a previously qualified model image, set
`SOORIN_MODEL_BUILD_REVISION` to its SHA, verify the corresponding image tag with
`run images`, and omit `run build-models` for that upgrade.
For a rollback record the previous image IDs, immutable tags, Git revision,
volume names, model settings and private configuration before any upgrade.

## Provision the caches

Use the existing qualified cache names whenever possible. Empty cache-name overrides
select `<project>_soorin_embedding_cache` and `<project>_soorin_reranker_cache`.
Only an enabled NER role needs a third snapshot. Set `cpu_image` to the actual built
image (below uses the template tag), and set the volume variable to its inventory name.
Check each existing snapshot offline before considering a download.

```bash
cpu_image="soorin-tkg-cpu:$(git rev-parse HEAD)"
role=embedding                    # repeat for reranker, and ner if enabled
cache="${project}_soorin_${role}_cache"
docker volume inspect "$cache" >/dev/null
docker run --rm --network none --read-only -v "$cache:/cache:ro" "$cpu_image" \
  verify-artifacts --role "$role" --cache /cache --hashes
```

For a **new cache only**, initialize a new named volume and give the model user
write access to its root. Populate using the same pinned image on an authorized
networked host, then repeat the offline hash verification. Investigate an invalid
existing cache before choosing any replacement.

```bash
docker volume create "$cache"
docker run --rm --network none --user 0:0 --entrypoint chown -v "$cache:/cache" \
  "$cpu_image" 65532:65532 /cache
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  -v "$cache:/cache" "$cpu_image" download --role "$role" --cache /cache
```

## Fresh installation

Set `SOORIN_VOLUME_MODE=fresh` in .env, choose an unused project and explicitly name
two new volumes. For example use `local_tkg_db_01` and `local_tkg_data_01`.
Use already provisioned model caches. Start with SOC integration off and restrict
the TLS proxy to the administrator during first-account bootstrap.

```bash
run config
run preflight
run up
run health
run status
```

Preflight checks the project inventory and volume names. After validating images,
up creates both new volumes and invokes Compose with builds and pulls disabled.
The init hook provisions utopia_app. Schema version 110 includes migration 10009.
Register the first administrator through the private HTTPS origin or direct HTTP
bound to loopback. In Admin → Deployment, close registration and confirm a second
unauthenticated registration is refused. The database registration setting takes
precedence over the environment fallback.
Set `SOORIN_VOLUME_MODE=preserve` before the next preflight or up. A failed first
start can leave volumes and containers for inspection. Inventory these before recovery.

## Preserve and upgrade

Select the **existing** project, named state volumes, existing credentials and keys
in .env. Set `SOORIN_VOLUME_MODE=preserve`. Back up PGDATA, application data and keys
as a matched set. Rehearse restore with the planned revision and compatible rollback
revision. On a historical deployment with a bind mount, first plan and verify a
controlled data copy/restore into a named volume. Preserve requires a matching existing
project app and DB, a live database and an authenticated runtime and owner login.
Validate existing role grants including restricted audit access before cutover.
If an old unified service or retired NER container belongs to the project, inventory,
stop and remove only that container under the approved plan, retaining its image and volumes.

```bash
run config
run build-app
run build-models
run images
run preflight
run up
run health
run status
```

Preflight checks both mounted identities, other volume consumers, model caches,
the existing signing and encryption keys, and the SQLx migration ledger against
the SHA-384 checksums of the reviewed sources. Missing historical versions,
unsuccessful migrations and checksum drift block cutover. Normal app startup
applies pending migrations as owner. If the project was intentionally stopped,
start only its existing DB container using its inspected ID before preflight.
An older app with a file-backed encryption key must also be available for verification.

## Integration and acceptance

Set `SOORIN_SOC_INTEGRATION=on` after bootstrap and inventory the external local bridge
`aisoc-tkg`. Only the app receives the alias `soorin-tkg` there. Verify
`http://soorin-tkg:1516` and independently qualify the scoped reader, ingest and
receipt-status credentials from authorized SOC services. Optional external-provider
DLP settings require a separately approved reachable gateway. This topology makes
no attachment to the privacy network.

Per-role CPU, memory, thread count, queue size and queue timeout are independent.
Set `SOORIN_MODEL_DIAGNOSTICS=on` temporarily for loopback 2811/2812. To opt in to
NER, provision its pinned read-only cache and set `SOORIN_ENABLE_NER=on`. Run config,
preflight, up and health. The app gains the 8082 internal origin. Diagnostic
publication covers only the first two roles. Confirm workspace model selection,
readiness, actual dense retrieval/reranking, and embedding availability during
a reranker-only restart. Record latency, queue pressure and rollback evidence.

## Stop, rollback and explicit image cleanup

```bash
run stop
```

Keep containers, volumes, caches and private config for recovery. For rollback first
quiesce writers. Restore the approved old checkout/config and its matching images.
Verify its embedded migration set accepts the applied SQLx ledger. When it does,
restart the inspected DB and run preserve preflight, up and health. Otherwise
use the rehearsed matched backup restoration on an isolated target before switching
traffic. Preserve the prior storage until acceptance.

After acceptance, select a **single superseded image tag**, verify its ID matches
the inventory, and inspect references from all containers. Preserve rollback images.
For an explicitly approved unused tag, use the following commands.

```bash
: "${old_tag:?specific retired image tag}" "${old_id:?recorded sha256 image ID}"
consumers=$(docker ps -aq --filter "ancestor=$old_id") &&
  test "$(docker image inspect -f '{{.Id}}' "$old_tag")" = "$old_id" &&
  test -z "$consumers" &&
  docker image rm "$old_tag"
```

Runtime acceptance requires a real approved deployment, recovery rehearsal, cache
verification, role-separated migrations, secure bootstrap, SOC receipt authorization
and measured isolated-role behavior. Compose qualification and synthetic tests
exercise deployment inputs and guards only.

## Server 55 direct LAN HTTP

The controlled development endpoint is `http://192.168.0.55:2516`. The Rust app
serves both the React HTML and API on that listener. The internal Nginx models
proxy continues to route embedding and reranking inside Compose. Source mode
defaults to `https-proxy`. Explicit `lan-http` permits a specific RFC 1918,
IPv6 ULA or loopback address with an exact matching HTTP origin and host port.
Use the IP literal, or `localhost` for a loopback bind. Omit the default HTTP
port from the origin if the published port is 80.

HTTP carries credentials, session cookies and application data **without
encryption**. Use only dedicated synthetic accounts and synthetic data. Limit
reachability to authorized development LAN networks at the network boundary and
avoid public routing or forwarding. Real organizational accounts and sensitive
SOC or investigation traffic require trusted encrypted transport. Use the
[immutable HTTPS deployment](SERVER55_PRODUCTION_RELEASE.md#canonical-hardened-production-interface)
for production.

LAN mode allows the app to issue its existing HTTP session cookie. It remains
HttpOnly and SameSite=Lax. Registration, login and logout use the same cookie
path and TLS detection. The frontend uses relative `/api/v1` URLs with
credentials. The CORS allow-origin stays exact. CORS governs browser access to
cross-origin responses and is distinct from CSRF protection. The mode preserves
existing SameSite behavior, request handlers, and workspace and KB authorization.

### Upgrade the existing source deployment

Use a reviewed commit available on the designated server remote. Verify backup
and rollback readiness and run the following on Server 55 during the change window.

```bash
cd /home/api/Soorin_TKG
: "${RELEASE_SHA:?set the reviewed full commit SHA}"
test "$(git branch --show-current)" = main &&
test -z "$(git status --porcelain)" &&
git fetch origin main &&
test "$(git rev-parse origin/main)" = "$RELEASE_SHA" &&
git merge --ff-only "$RELEASE_SHA" &&
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
```

Edit the **existing** mode-0600 `.env` in place. Keep the existing database
passwords and URLs, JWT and encryption keys, qualified database and Nginx
digests, and the rest of the deployment settings. Check these values against the
deployment inventory. Leave an existing matching value in place.

```dotenv
COMPOSE_PROJECT_NAME=soorin-tkg-server55
SOORIN_ACCESS_MODE=lan-http
SOORIN_APP_BIND=192.168.0.55:2516
SOORIN_PUBLIC_ORIGIN=http://192.168.0.55:2516
SOORIN_VOLUME_MODE=preserve
SOORIN_PROD_DB_VOLUME=soorin-tkg-server55_fresh_db_20261128
SOORIN_PROD_DATA_VOLUME=soorin-tkg-server55_fresh_data_20261128
SOORIN_EMBEDDING_CACHE_VOLUME=soorin-tkg-server55_soorin_embedding_cache
SOORIN_RERANKER_CACHE_VOLUME=soorin-tkg-server55_soorin_reranker_cache
SOORIN_NER_CACHE_VOLUME=soorin-tkg-server55_soorin_ner_cache
SOORIN_ENABLE_NER=off
SOORIN_MODEL_DIAGNOSTICS=off
SOORIN_SOC_INTEGRATION=off
SOORIN_MODEL_BUILD_REVISION=568b3aa7cd9497cb598506dc841f5b809b8483ca
SOORIN_BUILD_JOBS=1
SOORIN_DB_MAX_CONNECTIONS=8
SOORIN_RERANK_TIMEOUT_SECONDS=75
SOORIN_RERANK_DEADLINE_SECONDS=165
SOORIN_RERANK_MAX_CANDIDATES=16
SOORIN_RERANK_BATCH_SIZE=8
```

The model image reference must resolve to the existing qualified CPU image with
the selected revision label. With the template naming convention, keep
`SOORIN_CPU_MODEL_IMAGE=soorin-tkg-cpu:${SOORIN_MODEL_BUILD_REVISION}` and
`SOORIN_IMAGE=soorin-tkg-app:${SOORIN_BUILD_REVISION}`. An installation
using explicit local tags should keep its inspected CPU tag and select a new
app tag for the reviewed revision. This is a configuration-only change for the
app's HTTP behavior. The source policy still requires the app image's OCI revision
to match HEAD, so build the app with the existing BuildKit caches. Reuse the
qualified model image.

```bash
run() { python3 scripts/source_deploy.py "$@" --project soorin-tkg-server55; }
run config
run build-app
run images
```

The `images` command verifies app and CPU revision labels and the selected
third-party registry digests. It prints image IDs and provenance.
Before targeting the LAN address, complete private bootstrap if preserve
preflight reports that the administrator is missing or registration is open.
Temporarily set `SOORIN_APP_BIND=127.0.0.1:2516` and
`SOORIN_PUBLIC_ORIGIN=http://127.0.0.1:2516` in the same `.env`, keep preserve
mode, and run:

```bash
run config
run preflight
run up --app-only
run health
```

From the host's private loopback session, register the first synthetic
administrator if the database has no account, or sign in with the existing
synthetic administrator. In Admin → Deployment, turn off open registration.
Confirm that a second unauthenticated registration is refused. For a future
fresh install, use the loopback bind before first startup and switch to preserve
after bootstrap. Restore the exact LAN bind and public origin in `.env` after
these checks. Preserve preflight requires an administrator and closed
database-backed registration before direct LAN publication.

```bash
run config
run preflight
docker ps -a --filter publish=2516 --format '{{.ID}} {{.Names}} {{.Ports}}'
```

If the temporary TKG Caddy still owns the LAN port, select its exact container
ID from that listing and inspect it. Verify the name, image and publication
identify the temporary TKG proxy for `192.168.0.55:2516`.

```bash
: "${TKG_CADDY_ID:?set the inspected temporary TKG Caddy container ID}"
docker inspect --format '{{.Name}} {{.Config.Image}} {{json .HostConfig.PortBindings}}' "$TKG_CADDY_ID"
# Run only after confirming the inspected container is the temporary TKG proxy.
docker stop "$TKG_CADDY_ID" && docker rm "$TKG_CADDY_ID"
```

Recreate only the app and qualify direct HTTP from an authorized LAN client.

```bash
run up --app-only
run health
run status
base=http://192.168.0.55:2516
curl -fsS -o /dev/null -w '%{http_code} %{content_type}\n' "$base/"
curl -fsS "$base/api/v1/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$base/api/v1/auth/me"
```

Expect HTML and HTTP 200 for the frontend, healthy JSON for the API, and 401
for the unauthenticated session probe. In the browser, verify sign-in, the
session surviving refresh, logout, closed registration, and separate workspace
and knowledge-base permissions using synthetic accounts. Verify a successful
embedding and reranking request against the saved model configuration.

After the LAN checks, set `SOORIN_SOC_INTEGRATION=on` only for authorized synthetic
integration. Inspect the existing `aisoc-tkg` network, then run `run config`,
`run preflight`, `run up --app-only` and `run health`. From the authorized SOC
service, confirm `http://soorin-tkg:1516`, Reader, Ingest and Receipt Status scope
and a synthetic delivery. PostgreSQL and the model services stay on their
private networks. DLP continues using its separate HTTPS path.
