# Soorin TKG: isolated 5,500-alert HTTP acceptance

**Status:** Test plan and harness only. Production readiness is **not** established until recorded execution results pass the gates below.

## Preconditions

- Use a newly created Docker Compose project named `soorin-tkg-acceptance-5k`, not the current `soorin-tkg-v1-qa` lab.
- API must bind `127.0.0.1:2626`, DB `127.0.0.1:2627`; the project must own its DB/data volumes.
- Ensure `docker compose config --quiet`, app health, PostgreSQL migrations `10005`/`10006`, and a clean source build from the intended main commit.
- Make an isolated synthetic organization/workspace, knowledge base, immutable binding (`tenant-blue/splunk/splunk-e2e`), imported SOC ontology and **statements** Source. Export `KB_ID`, `SOURCE_ID`, `INGEST_TOKEN`, `SESSION_TOKEN` in the local shell, not in a log or Git.
- Do not use real customer alerts. The 5,500 dataset is generated from `soorin.tests.mock_splunk.scripts.curated_qa_dataset`.
- This tool does not create or delete Docker resources and will refuse non-disposable targets.

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
