# Server 55 app release

Execute on `192.168.0.55` during an approved release window. The last reported baseline was 111 bound and embedded synthetic alerts. A successful eight-pair POST to the model established reachability. The running Rust revision and the full Search result remain release gates.

## Synchronize the server checkout

Use the full SHA verified on both project remotes and on all required GitHub CI jobs. Run the following shell setup on Server 55 before choosing either method.

```bash
set -euo pipefail
umask 077
cd /home/api/Soorin_TKG
: "${RELEASE_SHA:?approved full SHA}"
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"
git remote -v
git remote get-url origin
git branch -vv
```

### Method A — authorized fetch

Confirm the origin URL identifies `SoorinSecurity/Soorin_Bidirectional_Temporal_Knowledge_Graph` and use organization-approved credentials. For an SSH origin, run `ssh -T git@github.com` with host verification enabled and check the account/deploy-key identity in the banner. GitHub can return exit 1 for a successful SSH authentication because it offers no shell. Check the actual repository permission with `git ls-remote origin refs/heads/main`. A wrong URL, wrong SSH identity, unenrolled deploy key or missing organization access can each yield “Repository not found.” A failed fetch leaves stale local tracking refs. An “Already up to date” merge against such a ref only describes local ancestry.

```bash
remote_tip=$(git ls-remote --exit-code origin refs/heads/main | cut -f1)
test "$remote_tip" = "$RELEASE_SHA"
git fetch --no-tags origin refs/heads/main
test "$(git rev-parse FETCH_HEAD)" = "$RELEASE_SHA"
git merge-base --is-ancestor HEAD "$RELEASE_SHA"
git merge --ff-only "$RELEASE_SHA"
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
```

### Method B — verified Git bundle

On the laptop, use the clean synchronized checkout with both remote tips freshly verified. Create the bundle inside an existing private transfer directory. Verify Server 55's SSH host key and use an existing owner-only `~/tkg-release-incoming` directory.

```bash
set -euo pipefail
umask 077
: "${RELEASE_SHA:?}" "${BUNDLE_DIR:?private transfer directory}"
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"
git fetch --no-tags origin main
git fetch --no-tags personal main
for ref in HEAD origin/main personal/main; do
  test "$(git rev-parse "$ref")" = "$RELEASE_SHA"
done
bundle="$BUNDLE_DIR/tkg-$RELEASE_SHA.bundle"
git bundle create "$bundle" refs/heads/main
test "$(git bundle list-heads "$bundle" refs/heads/main | cut -d ' ' -f1)" = "$RELEASE_SHA"
(cd "$BUNDLE_DIR" && sha256sum "${bundle##*/}" > "${bundle##*/}.sha256")
scp "$bundle" "$bundle.sha256" api@192.168.0.55:tkg-release-incoming/
```

On Server 55, compare the full advertised SHA against the independently approved release record. Verify the transfer and ancestry before merging into the existing checkout.

```bash
incoming="$HOME/tkg-release-incoming"
bundle="$incoming/tkg-$RELEASE_SHA.bundle"
(cd "$incoming" && sha256sum -c "${bundle##*/}.sha256")
git bundle verify "$bundle"
test "$(git bundle list-heads "$bundle" refs/heads/main | cut -d ' ' -f1)" = "$RELEASE_SHA"
git fetch --no-tags "$bundle" refs/heads/main
test "$(git rev-parse FETCH_HEAD)" = "$RELEASE_SHA"
git merge-base --is-ancestor HEAD "$RELEASE_SHA"
git merge --ff-only "$RELEASE_SHA"
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
```

## Identify the running app and dependencies

Supply organization-approved health URLs and an encrypted backup destination outside the Docker root. The earlier 32 GB free is a planning snapshot. Use the current disk and cache measurements. Preflight runs before building or quiescing producers.

```bash
: "${BACKUP_ROOT:?mounted private backup destination}" "${AGENTIC_HEALTH_URL:?}" "${DLP_HEALTH_URL:?}"
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
test -z "$(git status --porcelain)"
override=/home/api/tkg-fresh-volumes-20261123.yml
test -s "$override"
dc=(docker compose --env-file .env -p soorin-tkg-server55 -f docker-compose.soorin-dev.yml -f docker-compose.models.yml -f "$override" --profile models)
app=$("${dc[@]}" ps -q app)
db=$("${dc[@]}" ps -q db)
models=$("${dc[@]}" ps -q models)
test -n "$app" && test -n "$db" && test -n "$models"
tag=soorin-tkg-server55-app:latest
stamp=$(date -u +%Y%m%dT%H%M%SZ)
save="$BACKUP_ROOT/tkg-$stamp"
mkdir -m 700 "$save"
old=$(docker inspect -f '{{.Image}}' "$app")
rollback=soorin-tkg-server55-app:rollback-$stamp
test "$(docker image inspect -f '{{.Id}}' "$tag")" = "$old"
docker image inspect "$old" --format '{{.Id}} {{json .RepoDigests}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
docker inspect "$app" "$db" "$models" -f '{{.Id}} {{.State.StartedAt}} {{json .NetworkSettings.Ports}} {{json .Mounts}}' > "$save/runtime.txt"
docker inspect "$db" "$models" -f '{{.Id}} {{.State.StartedAt}} {{.Image}} {{json .Mounts}}' > "$save/dependencies.txt"
docker exec "$app" sha256sum /usr/local/bin/utopia-server > "$save/old-binary.sha256"
docker exec "$db" psql -XAt -U utopia -d utopia -c   "SELECT coalesce(json_agg(json_build_object('version',version,'checksum_hex',encode(checksum,'hex'))),'[]') FROM _sqlx_migrations WHERE success" > "$save/applied.json"
python3 -m soorin.ops.migrations --applied-json "$save/applied.json"
df -h / "$BACKUP_ROOT"
docker system df
docker buildx du
curl -fsS "$AGENTIC_HEALTH_URL" >/dev/null
curl -fsS "$DLP_HEALTH_URL" >/dev/null
"${dc[@]}" config --format json > "$save/compose.private.json"
export SOORIN_RELEASE_CONFIG="$save/compose.private.json" SOORIN_RELEASE_IMAGE="$tag"
python3 - <<'PY'
import json, os
from soorin.e2e.soc_production_reliability import SERVER, SERVER_URL, APP_VOLUME, DB_VOLUME
from soorin.e2e.reliability_5k_http import _docker_inspect, verify_server_target
verify_server_target(SERVER_URL, SERVER, 2517, APP_VOLUME, DB_VOLUME)
c = json.load(open(os.environ["SOORIN_RELEASE_CONFIG"]))
assert c["name"] == SERVER
app_image = c["services"]["app"].get("image") or f'{c["name"]}-app'
assert app_image in {os.environ["SOORIN_RELEASE_IMAGE"], os.environ["SOORIN_RELEASE_IMAGE"].removesuffix(":latest")}
assert c["services"]["models"]["image"] == "soorin-tkg-v1-qa-models:latest"
for service in ("app","db","models"):
    running = _docker_inspect(SERVER, service)
    bound = running["NetworkSettings"]["Ports"]
    actual_ports = {(port, row["HostIp"], row["HostPort"])
                    for port, rows in bound.items() for row in (rows or [])}
    planned_ports = {(f'{row["target"]}/{row.get("protocol", "tcp")}',
                      row.get("host_ip"), str(row["published"]))
                     for row in c["services"][service].get("ports", [])}
    assert planned_ports == actual_ports
    actual = {m["Destination"]:m["Name"] for m in running["Mounts"] if m["Type"]=="volume"}
    planned = {v["target"]:c["volumes"][v["source"]]["name"]
               for v in c["services"][service]["volumes"] if v["type"]=="volume"}
    assert planned == actual and planned
    if service == "models":
        assert set(actual)=={"/models/embedding","/models/reranker","/models/ner"}
        assert all(not m["RW"] for m in running["Mounts"] if m["Destination"] in actual)
        for port,host in [(8080,2811),(8081,2812),(8082,2813)]:
            assert running["NetworkSettings"]["Ports"][f"{port}/tcp"] == [{"HostIp":"127.0.0.1","HostPort":str(host)}]
    for mount in c["services"][service]["volumes"]:
        assert mount["type"]=="volume" and actual[mount["target"]]==planned[mount["target"]]
PY
```

Record image ID even if RepoDigests is empty for a local build. A missing revision label means historical binary provenance is unknown. Confirm the external override resolves the DB to `soorin-tkg-server55_fresh_db_20261123` and app data to `soorin-tkg-server55_fresh_data_20261123`. Allow space for a retained rollback image, intermediates and backups. Pause if the external mount, dependent service health, available space or backup destination differs from the approved inventory.

## Preserve rollback and build with the current app running

Use the existing cache, exact project and three Compose inputs. The build can compete for CPU and disk, so budget the window and check both resources before starting. Build only the app. A changed `latest` tag does not switch the running container. Keep any app recreation automation suspended until the cutover.

```bash
if docker image inspect "$rollback" >/dev/null 2>&1; then exit 1; fi
docker image tag "$old" "$rollback"
printf '%s\n' "$old" "$rollback" "$RELEASE_SHA" > "$save/release.txt"
export DOCKER_BUILDKIT=1 SOORIN_BUILD_REVISION="$RELEASE_SHA"
"${dc[@]}" build app
new=$(docker image inspect "$tag" -f '{{.Id}}')
test "$(docker image inspect "$new" -f '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$RELEASE_SHA"
test "$(docker inspect -f '{{.Image}}' "$app")" = "$old"
test "$(docker image inspect -f '{{.Id}}' "$rollback")" = "$old"
df -h / "$BACKUP_ROOT"
```

## Establish a consistent backup boundary and cut over

Quiesce producers and other writers to the TKG database, allow in-flight receipts to settle, then stop only the app. This is the downtime boundary. Keep the DB and models running. Rehearse restoring to an isolated target before this window and reserve enough time to validate the final backup set and encryption key before the recreate. Keep Compose, DB and app-data backups private.

```bash
"${dc[@]}" stop -t 90 app
docker exec "$db" pg_dump -U utopia -d utopia -Fc > "$save/db.dump"
docker exec "$db" pg_dumpall -U utopia --globals-only > "$save/globals.sql"
docker cp "$app:/app/data/." - > "$save/app-data.tar"
docker exec -i "$db" pg_restore --list < "$save/db.dump" > "$save/db-toc.txt"
tar -tf "$save/app-data.tar" > "$save/data-files.txt"
rg '(^|/)secret\.key$' "$save/data-files.txt" >/dev/null
test -s "$save/db-toc.txt" && test -s "$save/globals.sql"
install -m 600 .env "$save/.env"
install -m 600 "$override" "$save/${override##*/}"
(cd "$save" && sha256sum db.dump globals.sql app-data.tar > SHA256SUMS && sha256sum -c SHA256SUMS)
```

Require a verified restore of this backup set on an isolated restore target, confirm the encryption key can decrypt configuration and verify the selected recovery path before recreating the app. Archive listings alone do not validate restore. If the backup gate fails before recreation, the original app can be resumed with `"${dc[@]}" start app` while the existing database schema is intact.

```bash
test "$(docker image inspect -f '{{.Id}}' "$tag")" = "$new"
"${dc[@]}" up -d --no-deps --no-build --pull never --force-recreate app
app=$("${dc[@]}" ps -q app)
test "$(docker inspect "$app" -f '{{.Image}}')" = "$new"
docker exec "$app" sha256sum /usr/local/bin/utopia-server > "$save/new-binary.sha256"
curl --retry 30 --retry-all-errors --retry-delay 2 --max-time 5 --retry-max-time 150 -fsS http://192.168.0.55:2516/api/v1/health >/dev/null
docker inspect "$("${dc[@]}" ps -q db)" "$("${dc[@]}" ps -q models)" -f '{{.Id}} {{.State.StartedAt}} {{.Image}} {{json .Mounts}}' | diff - "$save/dependencies.txt"
docker exec "$db" psql -XAt -U utopia -d utopia -c 'SELECT version,success FROM _sqlx_migrations ORDER BY version DESC LIMIT 5'
"${dc[@]}" logs --tail 100 app | rg 'queue ownership acquired|jobs worker|migration|ERROR'
curl -fsS "$AGENTIC_HEALTH_URL" >/dev/null
curl -fsS "$DLP_HEALTH_URL" >/dev/null
```

Confirm migration 10008 succeeded, the exclusive queue owner started and the existing worker setting is intentional. Repeat mount/port preflight against the replacement app. Use the actual scoped reader for Search, resolve and context and the KB administrator for a known bound receipt. Require a populated current result with `dense_executed=true`, `lexical_method=tantivy_bm25` and `reranker_status=complete`. Record `complete`, `fallback`, and `disabled` distinctly. Under concurrent load, capture fallback frequency and the sanitized cause, including `search_capacity` when the foreground permit is held. This protects the shared CPU queue and can return useful RRF results without waiting behind a foreground request. For a historical result, inspect `postgres_versioned_lexical` and the record-time boundary. Validate external registration is closed administratively and that revoked credentials receive 401. The previous successful model POST and a new health response alone do not meet these gates.

## Run synthetic acceptance

Set `KB_ID`, `SOURCE_ID`, `INGEST_TOKEN`, `SESSION_TOKEN`, `SCOPED_READ_TOKEN` and `OTHER_KB_ID` from the operator secret store. Use an existing real second KB outside that reader's grant for the denial test. Ensure the reader is a viewer and cannot see admin receipt diagnostics. Confirm tenant and instance with the source owner. Run from the host with local Docker access. The harness uses API writes only for curated ingestion and reads aggregate measurements with transaction-read-only psql. It never provisions the target.

```bash
: "${COUNT:?choose 10 for the first gate}" "${START_INDEX:?unused range}" "${RUN_OUT:?new private directory}"
: "${TKG_TENANT:?}" "${TKG_INSTANCE:?}"
run=(python3 -m soorin.e2e.soc_production_reliability)
target=(--target-profile server --allow-existing-server --out "$RUN_OUT" --tenant-id "$TKG_TENANT" --source-instance "$TKG_INSTANCE")
"${run[@]}" prepare "${target[@]}" --count "$COUNT" --start-index "$START_INDEX" --workers 2 --rps 3
"${run[@]}" preflight "${target[@]}"
"${run[@]}" send "${target[@]}"
"${run[@]}" verify "${target[@]}" --deadline 14400 --interval 30
"${run[@]}" report --out "$RUN_OUT"
```

For disposable validation omit server flags and use an existing dedicated acceptance project, KB, Statements source and loopback ports 2626/2627. The manifest binds the project, source, KB, tenant and input digests. Resume with the same output directory and running app and DB containers. Use a new run after a deployment or manifest change. Offline reports summarize the verified snapshot and reject changed inputs or journals. Choose distinct index ranges and new directories for 10, 100, 500, 1,000 and 5,500. Review each verdict and monitor shared-host impact before escalating. A PASS records a particular workload and deployed revision. Preserve the release record with each run. For incomplete enrichment, inspect the model identity/availability and outstanding child jobs. After operator-authorized workspace backfill, rerun verify against the original journal. The administrative backfill endpoint considers up to 1,000 documents per call and may affect other KBs in that workspace.

## Rollback and reclamation

Compare `_sqlx_migrations` before and after deployment. Migration 10008 adds a nullable UUID and two partial indexes. It preserves all historical receipt values. The app runs SQLx migrations at startup. SQLx 0.8.6 rejects applied migrations absent from its embedded set. An image built from `3600a725` therefore cannot start against a database after migration 10008, even though the SQL change is additive. Confirm the actual rollback image against an isolated copy of the migrated database before deployment. If it predates an applied migration, plan either a compatible forward recovery image or an independently approved restore of the matched DB and app-data backup set. Stop for operator review if that recovery evidence is missing. Preserve the migration ledger. For a compatible schema, quiesce producers, check the recorded rollback tag still resolves to the recorded old ID and change only the app image.

```bash
test "$(docker image inspect "$rollback" -f '{{.Id}}')" = "$old"
printf 'services:\n  app:\n    image: %s\n' "$rollback" > "$save/rollback.yml"
"${dc[@]}" -f "$save/rollback.yml" up -d --no-deps --no-build --pull never --force-recreate app
test "$(docker inspect "$("${dc[@]}" ps -q app)" -f '{{.Image}}')" = "$old"
```

Repeat health, dependency, mount and read-only API gates. Restoring data requires a separate recovery decision. The app rollback does not roll back migrations. After successful acceptance, inventory older app rollback images with `python3 scripts/soorin_server55_cleanup.py --rollback-tag "$rollback"`. It requires the healthy current release to match latest. During an exclusive Docker maintenance window, individually authorize an old single-tag image with `--acceptance-passed --remove-id sha256:<full-id> --confirmed-tag <exact-old-tag>`. The script rechecks all running and stopped container references. Historical tag formats outside the allowlist stay protected.

## CI before the release

Use the repo's Rust toolchain and disposable PostgreSQL with pgvector. Set `UTOPIA_DATABASE_URL` exclusively to the CI database and require DB tests so a missing connection cannot silently skip them.

```bash
export UTOPIA_MODEL_TEST_MODE=1 UTOPIA_TEST_REQUIRE_DB=1
cargo test --locked -p utopia-server reranker
cargo test --locked -p utopia-server retrieval_tests
cargo test --locked -p utopia-server soc_runtime_tests -- --test-threads=1
cargo test --locked -p utopia-store enrichment_backlog_leaves_room_for_graph_work
cargo test --locked --workspace
```
