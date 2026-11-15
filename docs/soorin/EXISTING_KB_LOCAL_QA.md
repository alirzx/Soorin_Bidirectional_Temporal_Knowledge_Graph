# Existing-KB Soorin SOC QA: controlled local E2E

**Purpose:** Qualify a clean source-built Soorin app/DB using the already-created
`Soorin SOC Synthetic Lab` KB. **Never** reset/rename/delete the existing KB,
workspace, PostgreSQL volume, other Docker projects, or source artifacts. The
utilities here live on the host; adding them does **not** require rebuilding the
running Rust image.

## 0. Prerequisites and health (read only)

Run from the repository root:

```bash
cd /mnt/X/Soorin/soorin_bi_TKG/utopia
git status -sb
git rev-parse --short HEAD
docker compose --env-file .env -p soorin-tkg-v1-qa -f docker-compose.soorin-dev.yml ps
curl --fail-with-body -fsS http://127.0.0.1:2526/api/v1/health
docker exec soorin-tkg-v1-qa-db-1 psql -U utopia -d utopia -Atc \
  'SELECT COUNT(*) FROM _sqlx_migrations WHERE success=true'
docker exec soorin-tkg-v1-qa-db-1 psql -U utopia -d utopia -Atc \
  "SELECT extname,extversion FROM pg_extension WHERE extname='vector'"
```

Current source expects 105 migrations; a healthy HTTP response alone does not
prove source jobs, pgvector, evidence bindings or model inference.

## 1. Login (fix for invisible input prompt)

**Never put an interactive `input()` or `getpass()` inside `$(...)`**:
command substitution captures stdout, including the prompt. A heredoc also
consumes stdin so `input()` returns EOF.

Use a true interactive terminal:

```bash
python3 -m soorin.ops.qa_login
```

The helper displays the email/password prompts, performs
`POST /api/v1/auth/login`, and stores the session at
`~/.local/state/soorin-tkg-v1-qa/session.json` with mode 0600.
The token is **not printed**, exported or committed. Do not execute this
module through pipes, command substitution, a heredoc or a non-interactive CI
terminal. The QA operator reads the same protected file. For invalid credentials
it reports HTTP 401 and does not create a new account.

To avoid accidentally reusing a token from an earlier QA database, re-login
after every database reset. For suspected compromise, remove the local session
file and authenticate again; server-side revocation/session invalidation remains
an administrative responsibility.

## 2. Reuse the existing KB; import ontology only after preview

```bash
python3 -m soorin.ops.qa_existing_kb inspect
python3 -m soorin.ops.qa_existing_kb ids
```

For environment variables in the **current** trusted shell, use:

```bash
source <(python3 -m soorin.ops.qa_existing_kb ids)
echo "$UTOPIA_WORKSPACE_ID $UTOPIA_KB_ID"
```

This only discovers an existing KB by exact name. It deliberately refuses
multiple matches and **never creates or renames a workspace or KB**.

The ontology importer currently expects a session in its designated token
environment variable, unlike the QA operator. Load the token into the current
shell only for this invocation, then immediately unset it:

```bash
export UTOPIA_SESSION_TOKEN="$(python3 -c 'from soorin.ops.qa_login import load_token; print(load_token())')"
python3 -m soorin.ontology.importer --base-url http://127.0.0.1:2526 \
  --kb-id "$UTOPIA_KB_ID" --token-env UTOPIA_SESSION_TOKEN
# Only after reviewing that there are no ontology conflicts:
python3 -m soorin.ontology.importer --base-url http://127.0.0.1:2526 \
  --kb-id "$UTOPIA_KB_ID" --token-env UTOPIA_SESSION_TOKEN --apply
unset UTOPIA_SESSION_TOKEN
```

`--apply` is create-only with post-apply verification. Existing seed types
can cause totals greater than the 17 reviewed SOC entity / 15 relation types.

## 3. Immutable tenant/source binding

The KB is bound once to
`{tenant_id: tenant-blue, source_system: splunk, source_instance: splunk-e2e}`.
A Statements source named `Soorin Splunk Synthetic Alerts` is created only
if it is absent. Source IDs and source tokens belong to the API and must not
be copied into a repository file.

```bash
export SOORIN_DISPOSABLE_ACCEPTANCE=1
python3 -m soorin.ops.qa_existing_kb prepare --execute
python3 -m soorin.ops.qa_existing_kb inspect
```

This step uses the existing Docker ownership guard
(`soorin-tkg-v1-qa`, port 2526, Compose labels and exact QA volume names).
**If the KB was previously bound to different authority, stop**; never weaken
that invariant to force an ingest.

## 4. Dataset: deterministic and source-reviewed, not real customer telemetry

A local generator is committed at
`soorin/tests/mock_splunk/scripts/curated_qa_dataset.py`. The separately
downloaded `soorin_tkg_splunk_qa_240.zip` is an alternative fixture.
**Do not combine both**: they may contain the same alert source identities
with different canonical checksums. Select one dataset for a fresh KB.

Generate one deterministic dataset:

```bash
python3 -m soorin.tests.mock_splunk.scripts.curated_qa_dataset \
  --out "$HOME/.local/share/soorin-tkg-qa/run-20261115" \
  --count 240 --revisions 12
export QA_ALERTS="$HOME/.local/share/soorin-tkg-qa/run-20261115/alerts.jsonl"
export QA_REVISIONS="$HOME/.local/share/soorin-tkg-qa/run-20261115/revisions.jsonl"
```

Or, for the pre-downloaded ZIP, inspect `unzip -l` first, then extract to an
**empty**, local untracked directory and set `QA_ALERTS` and `QA_REVISIONS`
to its respective JSONL files. Both datasets are synthetic approximations of
Agentic_SOC Splunk connectors, not a certification of arbitrary Splunk schemas.

## 5. Dry-run, HTTP preview and first 10 receipts

```bash
python3 -m soorin.ops.qa_existing_kb validate --file "$QA_ALERTS" --count 10
python3 -m soorin.ops.qa_existing_kb preview --file "$QA_ALERTS" --count 10
python3 -m soorin.ops.qa_existing_kb ingest --file "$QA_ALERTS" --count 10 --execute
python3 -m soorin.ops.qa_existing_kb status --file "$QA_ALERTS" --count 10 --wait --deadline 1200
```

The operator stores **receipt IDs only** in a private local state file.
`status --wait` requires exactly the requested number of tracked receipts
and all statuses `bound`; it will not falsely pass after partial ingestion.
When a job or receipt stalls, stop bulk submission and inspect
`GET /api/v1/kbs/{kb}/knowledge/receipts/{receipt}` plus
`docker compose ... logs --tail=120 app`. Avoid mass retries and graph rebuild.

```bash
python3 -m soorin.ops.qa_existing_kb replay --file "$QA_ALERTS" --offset 0 --execute
python3 -m soorin.ops.qa_existing_kb search --file "$QA_ALERTS" --offset 0 --strict
```

Replay should reuse the original receipt. Core check verifies exact authority,
KnowledgeContext, graph overview and hybrid Search metadata; dense inference is
not considered verified unless `retrieval.dense_executed=true`.

## 6. Scale only after the 10-receipt gate

```bash
set -e
for part in '10 40' '50 50' '100 50' '150 50' '200 40'; do
  read -r offset count <<< "$part"
  python3 -m soorin.ops.qa_existing_kb ingest --file "$QA_ALERTS" \
    --offset "$offset" --count "$count" --execute
  python3 -m soorin.ops.qa_existing_kb status --file "$QA_ALERTS" \
    --offset "$offset" --count "$count" --wait --deadline 1200
done
```

Only after all base alert receipts are bound:

```bash
python3 -m soorin.ops.qa_existing_kb validate --file "$QA_REVISIONS" --count 12
python3 -m soorin.ops.qa_existing_kb preview --file "$QA_REVISIONS" --count 2
python3 -m soorin.ops.qa_existing_kb ingest --file "$QA_REVISIONS" --count 12 --execute
python3 -m soorin.ops.qa_existing_kb status --file "$QA_REVISIONS" --count 12 --wait --deadline 1200
```

Revision admission and bound status alone do not prove bitemporal correctness:
compare `at` and `as_of` contexts and current-version evidence separately.
Before any server release, execute native synthetic E2E, retry/restart,
tenant-isolation, model inference, MCP scoped PAT, DLP and provider acceptance.

## 7. Model and release gates

The running Rust app and DB need **no rebuild** after adding these host-side
QA scripts. Existing CPU model caches are separate and must be hash-verified
before combined `models` startup. Refer to
[Model artifact management](MODEL_ARTIFACT_MANAGEMENT.md),
[Model configuration](MODEL_CONFIGURATION.md) and
[Next local build acceptance](NEXT_APPROVED_BUILD_20261115.md).
A healthy `/api/v1/health` is not an end-to-end PASS.
