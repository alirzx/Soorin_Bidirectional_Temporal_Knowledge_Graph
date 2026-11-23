# Soorin TKG: isolated 5,500-alert HTTP acceptance

**Status:** Test plan and harness only. Production readiness is **not** established until recorded execution results pass the gates below.

## Preconditions

- Use a newly created Docker Compose project named `soorin-tkg-acceptance-5k`, not the current `soorin-tkg-v1-qa` lab.
- API must bind `127.0.0.1:2626`, DB `127.0.0.1:2627`; the project must own its DB/data volumes.
- Ensure `docker compose config --quiet`, app health, PostgreSQL migrations `10005`/`10006`, and a clean source build from the intended main commit.
- Make an isolated synthetic organization/workspace, knowledge base, immutable binding (`tenant-blue/splunk/splunk-e2e`), imported SOC ontology and **statements** Source. Export `KB_ID`, `SOURCE_ID`, `INGEST_TOKEN`, `SESSION_TOKEN` in the local shell, not in a log or Git.
- Do not use real customer alerts. The 5,500 dataset is generated from `soorin.tests.mock_splunk.scripts.curated_qa_dataset`.
- This tool does not create or delete Docker resources and will refuse non-disposable targets.


## Existing Server 55 acceptance (opt-in, same images)

The previous disposable-only test mode remains unchanged. This is a separate,
explicitly authorized profile for an already-running TKG QA server. The runner
**never** rebuilds Docker images, recreates containers, modifies Compose,
removes volumes, or deploys code. It only reads container metadata and sends
synthetic HTTP traffic to the **selected** KB/Statements source.

Server 55 configuration, as verified on 2026-11-23:

- Repository checkout: `/home/api/Soorin_TKG`, commit `90b0ee6`.
- Docker Compose project: `soorin-tkg-server55`.
- App: `http://192.168.0.55:2516` (private LAN).
- PostgreSQL: `127.0.0.1:2517` (loopback).
- Current app data volume: `soorin-tkg-server55_fresh_data_20261123`.
- Current database volume: `soorin-tkg-server55_fresh_db_20261123`.
- Model artifact/cache volumes are **not changed**.

### Preconditions and scope

1. Use the shell on Server 55 with access to Docker and the Git checkout.
   Confirm `git rev-parse HEAD` and image/DB health independently. Running
   this Python script does not require an application/container rebuild.
2. The `Default Workspace` and KB `SoorinSOC_Knowledge_Base` contain the
   SOC ontology (17 entity types, 15 relation types), tenant/source binding
   `tenant-blue/splunk/splunk-e2e`, and a `statements` source.
3. Source ID must be from that KB. `SESSION_TOKEN` is a KB administrator
   session; `INGEST_TOKEN` is the **source-specific** write credential.
   Never paste credentials into logs, command flags, reports or Git.
4. This KB contains the already-ingested smoke record
   `soc-alert-synthetic-00000`. Use `--start-index 1` to avoid it. For
   another 5,500-alert attempt against the **same source**, use a different,
   nonoverlapping start index or a new dedicated KB/source.
5. Explicit `--target-profile server --allow-existing-server` plus exact
   Compose project, DB port, expected app and DB Volume names are mandatory.
   The runner checks Docker ownership, mounts, and actual published ports,
   including LAN/loopback. The default disposable mode still rejects this
   existing deployment.
6. The server verification uses **only the unique receipt IDs acknowledged
   in the run journal**, not the entire pre-existing KB receipt totals.
   It pages the existing payload-free KB receipt endpoint, then samples graph
   diagnostics for materialized evidence. Missing or duplicate IDs fail.
7. Run bounded tests of 10 or 100 alerts first, inspect service pressure,
   and only then attempt 5,500. This is an operational load test on a server
   also hosting Agentic_SOC and DLP; choose an appropriate maintenance window.

### Commands (same Bash shell)

```bash
cd /home/api/Soorin_TKG
python3 -m unittest soorin.e2e.test_reliability_5k_http -v

export PROJECT=soorin-tkg-server55
export KB_ID=01a2077c-4257-7b10-ac10-baa234ebe307
export SOURCE_ID=01a20782-9d6c-7931-82d3-0a55df6bed66
export BASE_URL=http://192.168.0.55:2516
# Existing authenticated shell must export SESSION_TOKEN and INGEST_TOKEN.
test -n "${SESSION_TOKEN:-}" && test -n "${INGEST_TOKEN:-}" || exit 1

# Read-only container and volume check, without exposing tokens.
docker ps --filter "label=com.docker.compose.project=$PROJECT"
docker inspect soorin-tkg-server55-app-1 \
  --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}'
docker inspect soorin-tkg-server55-db-1 \
  --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}'

RUN_DIR="$HOME/tkg-test-runs/server55-5k-$(date -u +%Y%m%dT%H%M%SZ)"
COMMON=(
  --target-profile server --allow-existing-server
  --project "$PROJECT" --base-url "$BASE_URL"
  --db-port 2517
  --expected-app-volume soorin-tkg-server55_fresh_data_20261123
  --expected-db-volume soorin-tkg-server55_fresh_db_20261123
  --source-id "$SOURCE_ID" --kb-id "$KB_ID"
)
python3 -m soorin.e2e.reliability_5k_http \
  --mode prepare --out "$RUN_DIR" --count 10 --revisions 0 --start-index 1
python3 -m soorin.e2e.reliability_5k_http \
  --mode send --out "$RUN_DIR" "${COMMON[@]}" --workers 1 --rps 1
python3 -m soorin.e2e.reliability_5k_http \
  --mode verify --out "$RUN_DIR" "${COMMON[@]}" --deadline 1200 --sample 10
```

For the later **5,500-alert run**, choose a new `RUN_DIR`, use
`--count 5500 --start-index 11`, then repeat send/verify. Increase the
sampling and deadline deliberately after the 10/100 test. The sender defaults
to bounded retries; rerunning send resumes from `accepted.jsonl`.
Do not delete a partially successful run directory or reuse its indices in a
different run against the same source.

### Important limits and follow-up

- A successful `bound` receipt proves durable identity/graph binding, not
  execution of dense embeddings or reranking. Inspect search metadata:
  `dense_executed`, `lexical_method`, and `reranker_status`.
- This verifies source-scoped admissions, eventual binding, and sampled graph
  evidence; it is **not** a production benchmark without memory/CPU/IO,
  queue pressure, latency percentiles, and independent SQL verification.
- The previous worker default (64) may overwhelm the shared Server 55 CPU
  during high-volume tests. Measure and adjust deployment settings through
  documented administrative endpoints, **not** by changing Agentic_SOC/DLP.
- A failed receipt must be inspected through KB-scoped receipt diagnostics
  before any manual retry. Do not mass requeue unrelated jobs.
- Since the runner is outside the Docker image, editing/syncing its Python
  files requires **no** rebuilt images or container restart.


## Generate, send, verify

```bash
python3 -m unittest soorin.e2e.test_reliability_5k_http -v
python3 -m soorin.e2e.reliability_5k_http --mode prepare --out /mnt/X/Soorin/tkg-acceptance-5k --count 5500 --revisions 0
python3 -m soorin.e2e.reliability_5k_http --mode send --out /mnt/X/Soorin/tkg-acceptance-5k --workers 2 --rps 3
python3 -m soorin.e2e.reliability_5k_http --mode verify --out /mnt/X/Soorin/tkg-acceptance-5k --deadline 3600 --sample 20
```

Rerun `--mode send` to resume without duplicating acknowledged deliveries. Lost HTTP acknowledgements may be replayed; the server's canonical checksum/idempotency remains authoritative. Review `accepted.jsonl`, `failed.jsonl`, `send-report.json`, and `acceptance-report.json` without exposing credentials or raw events. The tool must not label any accepted receipt as `bound` until the status API confirms it.

To test revised events in the same source, create a **new** dataset directory with e.g. `--count 5500 --revisions 250`; use `--include-revisions` for send and verify. Confirm revision order against source clocks, not arrival order, and recognize that revision acceptance may intentionally quarantine stale/ambiguous records.

## Additional manual tests (not claimed by this harness)

1. **HTTP 429 / 503 and model restart**: prove graph materialization is independent of temporary embedding failure, then backfill vectors.
2. **Worker crash/restart**: interrupt the worker in the disposable stack, inspect orphan recovery, and demonstrate no duplicated entities or facts.
3. **Revision race**: replay the same canonical event, then submit a newer revision with controlled source clock; verify document_versions, current evidence, Tantivy and embeddings.
4. **Search / retrieval**: query exact identity resolution, BM25, dense retrieval, reranker and KnowledgeContext with a live configured model.
5. **Streaming semantics**: this is bounded concurrent individual HTTP POST admission, not SSE/Kafka native streaming or a proven continuous high-rate pipeline. Validate connector checkpoints/backpressure separately.
6. **Operational metrics**: capture duration, resource load, PostgreSQL query behavior, source queue age, failed child classes, p50/p95/p99 latency and sustained ingestion throughput.
7. **Security**: use isolated synthetic credentials, review authorization, cross-tenant negatives and redacted reports.

## Release gate

- 5,500 distinct admissions and 5,500 final `bound` receipts (or explain and manually approve legitimate quarantines).
- Zero loss, no duplicate source record binding, no orphaned jobs, no unrecoverable unexpected failures.
- Sampled evidence and graph diagnostics pass; independent SQL counts and search checks must corroborate this.
- Failure injection/restart and real CPU model/embedding backfill checks pass.
- All migrations, Rust unit/integration tests and Python tests pass. Record commit SHA, image digest, actual hardware/resources, runtime parameters, and results.
- The local `main` merge does not itself mean the Server 55 deployment is accepted.
