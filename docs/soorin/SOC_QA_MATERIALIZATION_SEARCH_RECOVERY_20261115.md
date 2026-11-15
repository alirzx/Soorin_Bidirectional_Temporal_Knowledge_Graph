# 2026-11-15 SOC ingestion / search local recovery gate

> Current existing-QA upgrade: follow [the application-only rebuild runbook](APP_ONLY_REBUILD_20261115.md) and [final source report](FINAL_SOURCE_HARDENING_20261115.md). Both running Compose labels identify **`.env`**, so pass `QA_ENV_FILE=.env`. Preserve the historical lab and both volumes; test new ingestion in a new synthetic KB. Earlier full-stack startup and v2-marker examples below are historical and are superseded for this upgrade.

**Scope:** Soorin TKG QA on `soorin-tkg-v1-qa`. Keep the original workspace,
`Soorin SOC Synthetic Lab`, Source, receipts, PostgreSQL/pgvector and all
Docker volumes. Do not delete, force-merge, or rewrite canonical identities.

## Evidence collected before patch

- 10 Curated SOC alerts accepted; 8 receipts bound, row 2 and row 8 submitted.
- Current Document and graph processing are completed for both.
- Row 8: the same `SOCCase` canonical key resolves to **two live entities**;
  one has the correct `soc_case` type, the other is authority-linked but untyped.
  All 11 reviewed relations have evidence, so the receipt is blocked by identity.
- Row 2: the same duplicate Case issue plus untyped SecurityEvent, SplunkNotable
  and UserAccount. Six reviewed relations lack current-version typed evidence.
- Search: 10 live indexed chunks. `synthetic`, `SecurityAlert` and `splunk`
  each return 10 hits; `Password` and `Password Spray Detection` returned zero
  before the v2 case-folding analyzer. Dense/reranker not configured.
- The queued `soc_ingest` jobs for rows 2 and 8 are waiting, not exhausted:
  retries cannot create missing type/evidence when a shared canonical key is split.

## Patch intent

1. Curated pushed Statements with opaque `soorin:` keys resolve by exact key
   and reviewed entity type. Other Utopia sources still use ordinary fuzzy
   resolution and human adjudication.
2. Same-key concurrent writes share an advisory lock. If legacy data contains
   multiple live rows or the authority registry disagrees, **fail closed**
   rather than silently merge. Do not weaken the existing identity registry.
3. Tantivy uses the same lowercase Jieba analyzer for indexing and queries.
   On startup the derived search index gets a one-time versioned rebuild
   from PostgreSQL chunks. No source documents or graph rows are deleted.

## Development/CI gate

Run unit and isolated real-DB tests against a dedicated empty **test**
database (never the QA DB):

```bash
cargo fmt --all -- --check
cargo test -p utopia-search soc_rule_titles_are_recalled_independent_of_case
cargo test -p utopia-store --test soc_curated_canonical_identity
```

Check CI before merging. A passing unit test does not prove end-to-end
receipt materialization; that must run against an isolated fresh KB.

## Preserve volumes across application-only upgrade

```bash
git status -sb
git fetch personal
git switch main
git pull --ff-only personal main
make qa-build QA_ENV_FILE=.env
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml up -d --no-deps --force-recreate app
docker compose --env-file .env -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml ps
```

The app-only replacement retains existing PostgreSQL and app-data volumes.
Watch the application startup log for
`search analyzer v2 migration complete`; a warning or absence of this
message is **not** a pass. Compare pre/post document counts and graph counts.

The **old KB still contains duplicated, pre-patch entities**. The patch does
not silently repair old identities, and a retry of existing receipts is
**not** an acceptable substitute for a reconciliation plan. Preserve this
KB as diagnostic evidence. Prefer first running the repository's native E2E
in a disposable KB or create a separate `Soorin SOC Patch Validation` KB
within the same existing Workspace. The `qa_existing_kb` operator accepts
`--kb-name` to select that new KB. Import the same reviewed SOC ontology
to the new KB, bind the same test tenant/source, and ingest the same ten
synthetic records. Verify 10/10 bound, zero duplicate canonical keys, and
nonzero query results for `Password` and `synthetic`. Only then scale
to 240 alerts and 12 revisions.

## Read-only diagnostics for preserved original KB

```sql
SELECT e.canonical_name, count(*) AS live_entity_rows,
       array_agg(e.id ORDER BY e.id) AS entity_ids
FROM entities e
WHERE e.kb_id = :'kb_id'::uuid AND e.merged_into IS NULL
  AND e.canonical_name LIKE 'soorin:%'
GROUP BY e.canonical_name HAVING count(*) > 1
ORDER BY live_entity_rows DESC LIMIT 30;
```

Never `UPDATE soorin_canonical_identities` or `DELETE FROM entities` by hand:
merges affect temporal facts, evidence and historical graph interpretation.
Any old-KB recovery requires a reviewed plan and separate backup.

## Release gate

No server promotion until an isolated fresh-KB E2E succeeds for 10/10,
then 240/240 and 12 revisions, exact resolution, typed/evidence-bound
relationships, tenant isolation, lexical and dense retrieval, GraphRAG
citations, scoped MCP PAT, privacy+LLM acceptance, safe restart and backup.
