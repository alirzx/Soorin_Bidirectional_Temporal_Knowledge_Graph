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
| app | Runtime login utopia_app, migration owner utopia, named /app/data, TLS proxy to loopback 2516 | 2 CPUs / 2 GiB |
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

[The environment template](../../.env.example) includes project and lifecycle, explicit database and app-data volumes, cache names, TLS origin and app binding, pool size, separate owner/runtime passwords and URLs, signing and encryption keys, image references, BuildKit inputs and mirrors, per-role budgets, optional diagnostics, SOC and DLP. Use `postgres://utopia_app:<encoded-runtime-password>@db:5432/utopia` and `postgres://utopia:<encoded-owner-password>@db:5432/utopia`. Supply a high-entropy signing secret and a 32-byte encryption key. The runner stamps both images with the full checkout SHA. Stage approved DB and nginx digest references locally before cutover. Keep build concurrency at one for a constrained builder.

Choose one project for the whole lifecycle. These commands render and validate actual
Compose inputs and print the project, lifecycle and service names. Direct Compose
config output includes resolved credentials. Clear stale exported deployment variables
before invoking the runner (shell values take precedence over dotenv).

```bash
scripts/source_deploy.py config --project soorin-tkg-local
scripts/source_deploy.py config --project soorin-tkg-server55
```

The runner orders the production base, isolated workers and source overrides, then
the optional SOC, diagnostic and NER overlays. Legacy Makefile QA targets use their
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
Register the first administrator through the private HTTPS origin, confirm a second
unauthenticated registration is refused, then grant normal access.
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
