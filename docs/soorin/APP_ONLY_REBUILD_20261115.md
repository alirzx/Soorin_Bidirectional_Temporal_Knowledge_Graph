# Existing QA: bounded application-only rebuild and acceptance

**Future separately approved session only.** None of the backup, build, stop,
start or acceptance writes below were executed in the source-hardening pass.
Read-only labels, ports, volumes, Compose configuration, UID, Python import,
tar and pg_dump availability were checked. Restore/build/runtime execution
remains to be qualified. Use one trusted Bash/Zsh shell from the repository.

## 1. Exact source and deployment preflight

```bash
cd /mnt/X/Soorin/soorin_bi_TKG/utopia
git status --short --branch
git rev-parse HEAD personal/main origin/main
free -h
df -h . /tmp
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker inspect soorin-tkg-v1-qa-app-1 soorin-tkg-v1-qa-db-1 \
  --format '{{.Name}} project={{index .Config.Labels "com.docker.compose.project"}} env={{index .Config.Labels "com.docker.compose.project.environment_file"}} files={{index .Config.Labels "com.docker.compose.project.config_files"}} image={{.Image}} user={{.Config.User}} mounts={{json .Mounts}} ports={{json .NetworkSettings.Ports}}'
docker volume inspect soorin-tkg-v1-qa_soorin_sprint1_data \
  soorin-tkg-v1-qa_soorin_sprint1_db --format '{{.Name}} {{json .Labels}}'
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml config --quiet
make qa-config QA_ENV_FILE=.env
```

Stop for dirty source, SHA mismatch, missing exact-SHA green CI, label/mount/port
drift or insufficient memory/disk. Do not substitute `.env.qa`: both running
containers identify **`.env`**. Expected ports are app 127.0.0.1:2526 and DB
127.0.0.1:2527. Preserve passwords, `.env`, `.env.qa` and model volumes.
`make qa-env-init` is only for a genuinely new environment; do not run it here.
Config is checked with `--quiet` because full output contains secrets.

Current old image IDs (recheck before use):

- app `sha256:cd68c6513caa2e9fbe1604de834ac76358ee0e6505dbc3dfaad6592d6a9cf45b`
- DB `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`

No model container was running during this pass. Existing dev QA does not have
production's runtime-role separation, read-only root filesystem or resource
limits. Do not claim those runtime properties from static production config.

## 2. Consistent backup and original-image rollback pin

Plan app downtime for backup and the single bounded build. PostgreSQL stays
running throughout. Disable external writers to this QA database; confirm no
other process writes it. Stop **only app**, then take the DB and app-data copy
while its workers cannot change either. A live tar without this quiescence is
not a coordinated source-state backup. Choose an access-controlled directory on
a disk with space; the backup contains sensitive application keys and DB data.

```bash
umask 077
export SOORIN_QA_BACKUP="/tmp/soorin-qa-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$SOORIN_QA_BACKUP"
git rev-parse HEAD > "$SOORIN_QA_BACKUP/new-source-sha.txt"
docker inspect soorin-tkg-v1-qa-app-1 --format '{{.Image}}' \
  > "$SOORIN_QA_BACKUP/old-app-image.txt"
docker image tag "$(cat "$SOORIN_QA_BACKUP/old-app-image.txt")" soorin-tkg-qa-rollback:pre-hardening
cp -p .env "$SOORIN_QA_BACKUP/env"
cp docker-compose.soorin-dev.yml "$SOORIN_QA_BACKUP/compose.yml"
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml stop -t 60 app
# Check app is stopped and DB is still healthy before continuing.
docker ps -a --filter name=soorin-tkg-v1-qa --format 'table {{.Names}}\t{{.Status}}'
docker exec soorin-tkg-v1-qa-db-1 pg_dump -U utopia -d utopia -Fc \
  > "$SOORIN_QA_BACKUP/database.dump"
docker exec soorin-tkg-v1-qa-db-1 pg_dumpall -U utopia --globals-only \
  > "$SOORIN_QA_BACKUP/globals.sql"
# docker cp supports a stopped container; it reads the mounted app-data volume.
docker cp soorin-tkg-v1-qa-app-1:/app/data "$SOORIN_QA_BACKUP/app-data"
tar -C "$SOORIN_QA_BACKUP" -cpf "$SOORIN_QA_BACKUP/app-data.tar" app-data
docker exec -i soorin-tkg-v1-qa-db-1 pg_restore --list \
  < "$SOORIN_QA_BACKUP/database.dump" > "$SOORIN_QA_BACKUP/database-toc.txt"
tar -tf "$SOORIN_QA_BACKUP/app-data.tar" > "$SOORIN_QA_BACKUP/app-data-files.txt"
sha256sum "$SOORIN_QA_BACKUP/database.dump" "$SOORIN_QA_BACKUP/app-data.tar" \
  > "$SOORIN_QA_BACKUP/SHA256SUMS"
docker exec -i soorin-tkg-v1-qa-db-1 psql -X -U utopia -d utopia \
  -v kb_id=01a1de1a-b112-7102-ad27-9eb8923b8a2f \
  < soorin/ops/qa_source_inventory.sql > "$SOORIN_QA_BACKUP/before.txt"
docker exec soorin-tkg-v1-qa-db-1 psql -X -U utopia -d utopia -Atc \
  "SELECT COALESCE(json_agg(x),'[]'::json) FROM (SELECT version,encode(checksum,'hex') AS checksum_hex FROM _sqlx_migrations WHERE success ORDER BY version) x" \
  > "$SOORIN_QA_BACKUP/applied-migrations.json"
python3 -m soorin.ops.migrations --applied-json "$SOORIN_QA_BACKUP/applied-migrations.json"
```

Check **each** exit code and nonempty backup files before proceeding; do not
run a shell batch that ignores failed commands. Move a verified copy off the
temporary filesystem. `pg_restore --list` checks readability, not restorability:
restore into a separately provisioned disposable instance and verify data,
keys, roles and checksums before replacement. No restore into current QA.
Docker cp retains contents/modes; archive ownership reflects the invoking host
user. If a later approved restore is needed, restore only into fresh volumes
and verify `/app/data` ownership 65532:65532, key modes and API decryptability.

If backup/restore or build cannot proceed, restart the original stopped app
with `docker start soorin-tkg-v1-qa-app-1`; this preserves its original image,
configuration and volumes. Do not run `qa-up`, `down`, prune or DB recreation.

## 3. Build once; replace app only

Host build memory remains a prerequisite; `CARGO_BUILD_JOBS=1` limits compiler
concurrency, not total memory. Existing host had ~4 GiB available and nearly
full swap: free capacity through a separately agreed operational action if
needed. Do not load models while building, reinstall toolchains or clear caches.

```bash
SOORIN_BUILD_JOBS=1 timeout 1800s make qa-build QA_ENV_FILE=.env \
  > "$SOORIN_QA_BACKUP/build.log" 2>&1
# Continue only on exit 0. A timeout/failure is a stop, not an automatic retry.
docker image inspect soorin-tkg-v1-qa-app --format '{{.Id}}' \
  > "$SOORIN_QA_BACKUP/new-app-image.txt"
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml up -d --no-deps --no-build --pull never --force-recreate app
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml ps
docker inspect soorin-tkg-v1-qa-app-1 --format '{{.Image}} {{json .Mounts}} {{json .NetworkSettings.Ports}}'
docker logs --since 10m soorin-tkg-v1-qa-app-1 \
  > "$SOORIN_QA_BACKUP/startup.log" 2>&1
curl --fail --max-time 10 -fsS http://127.0.0.1:2526/api/v1/health
docker exec soorin-tkg-v1-qa-app-1 id
docker exec soorin-tkg-v1-qa-app-1 python3 -S -c 'import sys;sys.path.insert(0,"/app");import soorin.ops.http_adapter'
```

Compose's generated image name is `soorin-tkg-v1-qa-app` for this project; verify
it via `docker compose ... config --images` if Compose behavior differs. Record
final Git SHA alongside the immutable image ID; this Dockerfile has no automatic
Git revision label, so title labels alone cannot establish source provenance.
Recheck the **same two volume names** and DB container/image/ID unchanged.

Startup must retain the 105 successful migration checksums (latest 10004) and
emit `search analyzer v3 recovery ready`. The first corrected startup rebuilds
derived Tantivy postings from live chunks before binding HTTP/starting workers.
Marker `/app/data/index/.soorin-jieba-lowercase-v3` contains
`jieba-lowercase-v3-live-documents` plus newline. Verify actual search directory
in `main.rs`/running config before inspection. Missing marker, recovery error or
timeout is a failure; health alone cannot prove graph/search readiness. No
schema changes were introduced in this pass.

```bash
docker exec -i soorin-tkg-v1-qa-db-1 psql -X -U utopia -d utopia \
  -v kb_id=01a1de1a-b112-7102-ad27-9eb8923b8a2f \
  < soorin/ops/qa_source_inventory.sql > "$SOORIN_QA_BACKUP/after.txt"
diff -u "$SOORIN_QA_BACKUP/before.txt" "$SOORIN_QA_BACKUP/after.txt"
```

Document/chunk/source graph/evidence/authority counts must not drop during a
derived-index conversion. Existing pending workers can change job/receipt state;
document every delta rather than force counts equal. Duplicate historical keys
should remain visible. New code may terminally flag their old jobs. Do not retry
or reconcile them to make acceptance pass. Compare counts on a subsequent
approved **app-only** restart too; marker reuse should report `rebuilt=false`
when live count is unchanged. No DB restart is necessary.

## 4. New-KB deterministic native acceptance

Authenticate normally with `python3 -m soorin.ops.qa_login`. Native harness reads
`UTOPIA_SESSION_TOKEN`, so load it without printing it, run, then unset. It
authenticates this session and creates a new synthetic workspace/KB; registration
remains closed and old workspace model settings remain untouched.

```bash
export UTOPIA_SESSION_TOKEN="$(python3 -c 'from soorin.ops.qa_login import load_token;print(load_token())')"
SOORIN_DISPOSABLE_ACCEPTANCE=1 timeout 1800s python3 -m soorin.e2e.native_validation \
  --base-url http://127.0.0.1:2526 --qa-project soorin-tkg-v1-qa --approved-port 2526 \
  --execute --deadline 300 --report /tmp/soorin-native-final-acceptance.json
unset UTOPIA_SESSION_TOKEN
```

Read every report stage; a missing/NOT RUN stage is not acceptance. This fixture
gate covers deterministic registry/materialization/replay/temporal contracts.
It does not replace the ten-alert producer gate or CPU-model acceptance.

## 5. Ten alerts, then 240 and 12 revisions

In the UI create a **new restricted KB**, named uniquely, e.g.
`Soorin SOC Final Source Validation 20261115`, in a synthetic workspace with dense
models disabled for the deterministic gate. Never select the historical lab.
Set `SOORIN_GATE_KB` to this exact unique name. Discover its IDs with
`qa_existing_kb ids --kb-name "$SOORIN_GATE_KB"`, then use the reviewed create-only
ontology preview/apply commands in [existing-KB QA](EXISTING_KB_LOCAL_QA.md) for
this new KB ID. Expect the 17 reviewed classes and 15 reviewed relation types
(plus any seed types); stop on conflict. Every operator command must include
`--kb-name` because its default selects the old lab.

```bash
export SOORIN_GATE_KB='Soorin SOC Final Source Validation 20261115'
export SOORIN_DISPOSABLE_ACCEPTANCE=1
source <(python3 -m soorin.ops.qa_existing_kb ids --kb-name "$SOORIN_GATE_KB")
export UTOPIA_SESSION_TOKEN="$(python3 -c 'from soorin.ops.qa_login import load_token;print(load_token())')"
python3 -m soorin.ontology.importer --base-url http://127.0.0.1:2526 \
  --kb-id "$UTOPIA_KB_ID" --token-env UTOPIA_SESSION_TOKEN
# Inspect preview for conflicts before the create-only apply:
python3 -m soorin.ontology.importer --base-url http://127.0.0.1:2526 \
  --kb-id "$UTOPIA_KB_ID" --token-env UTOPIA_SESSION_TOKEN --apply
unset UTOPIA_SESSION_TOKEN
python3 -m soorin.tests.mock_splunk.scripts.curated_qa_dataset \
  --out /tmp/soorin-final-240 --count 240 --revisions 12
export QA_ALERTS=/tmp/soorin-final-240/alerts.jsonl
export QA_REVISIONS=/tmp/soorin-final-240/revisions.jsonl
python3 -m soorin.ops.qa_existing_kb prepare --kb-name "$SOORIN_GATE_KB" --execute
python3 -m soorin.ops.qa_existing_kb validate --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --count 10
python3 -m soorin.ops.qa_existing_kb preview --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --count 10
python3 -m soorin.ops.qa_existing_kb ingest --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --count 10 --execute
python3 -m soorin.ops.qa_existing_kb status --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --count 10 --wait --deadline 1200
python3 -m soorin.ops.qa_existing_kb accept --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --count 10
python3 -m soorin.ops.qa_existing_kb replay --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --offset 0 --execute
```

`accept` is read only. Require 10 bound, source/version-matched graph evidence,
one graph UUID for each shared canonical key including shared Cases, exact
Alert authority resolution, title present in the same document's returned chunk,
Tantivy metadata and zero duplicate canonical keys in the new KB inventory.
Capture baseline temporal queries before corrections. If any assertion fails,
inspect bounded diagnostics and stop bulk ingestion; do not requeue everything.

Only after this first gate succeeds:

```bash
python3 -m soorin.ops.qa_existing_kb ingest --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --offset 10 --count 230 --execute
python3 -m soorin.ops.qa_existing_kb status --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --count 240 --wait --deadline 1800
# Sample each batch with accept before revisions, or cover all in batches of 10.
for soorin_offset in {0..230..10}; do
  python3 -m soorin.ops.qa_existing_kb accept --kb-name "$SOORIN_GATE_KB" --file "$QA_ALERTS" --offset "$soorin_offset" --count 10 || exit 1
done
# Proceed only if every batch and inventory succeeded; do not continue after a failure.
python3 -m soorin.ops.qa_existing_kb preview --kb-name "$SOORIN_GATE_KB" --file "$QA_REVISIONS" --count 12
python3 -m soorin.ops.qa_existing_kb ingest --kb-name "$SOORIN_GATE_KB" --file "$QA_REVISIONS" --count 12 --execute
python3 -m soorin.ops.qa_existing_kb status --kb-name "$SOORIN_GATE_KB" --file "$QA_REVISIONS" --count 12 --wait --deadline 1800
```

Then verify revision ordering, original identity UUIDs, current and historical
`at`/`as_of`, unchanged original evidence recording times and replay deduplication.
Do not run base-record current-version assertions after revisions and interpret
their failure as corruption: diagnostics intentionally describe current evidence.
Complete lexical/hybrid retrieval, GraphRAG citations, scoped MCP, then privacy/
agent acceptance per [next-stage gates](NEXT_APPROVED_BUILD_20261115.md). Qualify
cached model hashes before model startup; no implicit download is authorized.

## 6. Rollback without replacing original volumes

If the new image fails, preserve logs and source inventory. Create a temporary
Compose override with `app.image: soorin-tkg-qa-rollback:pre-hardening`, then run
only app with the **same** `.env`, project, base file and named volumes:

```bash
printf 'services:\n  app:\n    image: soorin-tkg-qa-rollback:pre-hardening\n' \
  > "$SOORIN_QA_BACKUP/rollback.yml"
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml -f "$SOORIN_QA_BACKUP/rollback.yml" \
  up -d --no-deps --no-build --pull never --force-recreate app
```

No schema change requires rollback migration. The old image may convert the
derived index under its own analyzer marker; that is not a source-data restore.
If source corruption is suspected, stop app and review backup/restore into
**fresh** volumes before any restore decision. Never overwrite current QA
volumes with a tar/SQL restore or delete its historical KB during rollback.
