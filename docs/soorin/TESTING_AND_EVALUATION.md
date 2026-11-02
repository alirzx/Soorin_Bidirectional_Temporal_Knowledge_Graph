# Testing and evaluation

## Standard offline gates

```bash
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m compileall -q soorin
python3 -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
python3 -m soorin.e2e.local_validation --report /tmp/soorin-e2e-offline.json
```

The Sprint 1 suite covers schema/version/timestamps/checksums/size, duplicate source events, identity collisions and aliases, deterministic extraction, Agentic payload variants, ontology validation/import behavior, lifecycle revisions, Statements limits/transport failures, model settings/fakes, reranker failure/fallback cases, tenant/time retrieval, and evaluation reports.

## Utopia regression gates

```bash
cargo fmt --all -- --check
cargo check --workspace
cargo test --workspace
cd web
pnpm test
pnpm typecheck
pnpm build
```

Database-backed tests require an isolated database. Do not reinterpret missing database/toolchain/model credentials as passing tests. Live model checks must identify endpoint/model/dimension and distinguish them from injected fake transports.

## Evaluation stages

Report these separately:

1. Contract normalization.
2. Statements document ingestion.
3. Open statement extraction.
4. Type and relation alignment.
5. Identity resolution.
6. Typed graph materialization.
7. Current/historical graph queries.
8. BM25/dense/hybrid/reranked retrieval.

An HTTP `created` response proves stage 2 only. `soorin/evaluation/graph_integrity.py`
validates pre-ingestion graph inputs and produces JSON. The isolated
`soorin.e2e.local_validation` harness records ingestion actions, KB-wide failed
job count, actual graph responses, typed graph assertions, historical queries,
and search results independently. Its offline default records live checks as
`NOT RUN`; live mode is opt-in and rejects the existing `1516` lab. See [Local
E2E validation](LOCAL_E2E_VALIDATION.md).

## Synthetic-data rule

All committed fixtures carry `synthetic: true`, use reserved example domains/test IP ranges, and contain no organization-specific logs or identities. Tests refuse or avoid unlabeled production datasets.

The live E2E fixture's cross-tenant row is used only by offline identity checks;
live mode writes only `tenant-blue` rows to the explicitly selected isolated KB.
