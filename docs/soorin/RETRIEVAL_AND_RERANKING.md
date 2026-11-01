# Retrieval and reranking

## Utopia baseline

`crates/utopia-server/src/retrieval.rs` runs Tantivy BM25 and pgvector in parallel, fuses up to 24 candidates per channel using deterministic RRF, then reloads eligible chunks. Missing embeddings/provider failures degrade to BM25; database/vector-query failures remain errors.

## SOC foundation

`soorin/retrieval/foundation.py` provides a reusable offline/test layer with:

1. Tenant/time filtering.
2. Exact identifier lookup before scoring.
3. BM25 keyword ranking.
4. Dense cosine ranking through a configurable embedder.
5. Reciprocal rank fusion and ID deduplication.
6. Optional cross-encoder reranking.
7. Provenance/evidence preservation and explicit status metadata.

Statuses are `complete`, `partial`, `fallback`, and `unavailable`. Metadata includes query ID, methods/models, score type, candidate/returned count, temporal filters, latency, and provider failure codes. Scores are ranking signals, never the probability an alert is malicious.

Exact matches bypass reranking. Reranker inputs are bounded; duplicate candidates retain the first stable candidate; ties use original rank then ID. Provider timeout/malformed/missing output preserves original RRF order when fallback is enabled. Reranking is disabled by default until a live benchmark demonstrates a useful quality/latency tradeoff.

## Historical limitation

Tantivy stores current chunks. An `as_of` query filters current hits to avoid false historical hits but cannot recall a chunk that existed then and was later replaced. Full historical BM25 correctness is not claimed. Fixing it requires a versioned full-text index and is outside this sprint.

## Offline benchmark

`python3 -m soorin.evaluation.retrieval_benchmark` compares BM25, BM25+dense+RRF, and BM25+dense+RRF+reranker. It emits Recall@K, MRR, nDCG@K, p50/p95 latency, and failure rate using synthetic SOC queries.
