# Testing and evaluation

## Standard offline gates

```bash
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 -m unittest discover -s soorin/tests -p 'test_*.py' -v
python3 -m compileall -q soorin
python3 -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
python3 -m soorin.evaluation.temporal_cases
python3 -m soorin.evaluation.retrieval_benchmark
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

An HTTP `created` response proves stage 2 only. `soorin/evaluation/graph_integrity.py` validates pre-ingestion graph inputs and produces JSON; a future live harness must record Utopia job/materialization outputs independently.

## Synthetic-data rule

All committed fixtures carry `synthetic: true`, use reserved example domains/test IP ranges, and contain no organization-specific logs or identities. Tests refuse or avoid unlabeled production datasets.
