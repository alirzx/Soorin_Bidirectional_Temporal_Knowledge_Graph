# Native retrieval, historical search and grounded context

Utopia remains the only graph/search engine. PostgreSQL is authoritative.
Current text search uses Tantivy BM25; dense pgvector results use the configured
embedding fingerprint. Each channel recalls up to 24 candidates, then RRF
deduplicates IDs. KB and record-time filters run during database reload before
reranking and final top_k. The recall ceiling is 48, independent of a larger
requested top_k.

Historical queries use PostgreSQL versioned lexical recall over chunks/documents
live at as_of, not today's Tantivy index. Terms use the simple text-search
configuration, OR recall, ts_rank_cd ranking, and stable UUID tie breaking.
This is not BM25 and has no promised phrase/operator/score equivalence to
Tantivy. Persian Unicode terms are retained by simple configuration; neither
route promises stemming equivalence across languages. Empty/punctuation-only
historical terms return no matches. Future records cannot consume historical
candidate limits.

Native TEI reranking scores a bounded prefix of the authorized RRF order. It
validates complete unique indices and finite scores. Ties retain original
order. The final result appends the untouched RRF tail when requested. A
failed batch restores the original RRF list when fallback is enabled.

The response includes an opaque `request_id`, `retrieved_candidate_count` (same
raw hit count as legacy `candidate_count`), `unique_candidate_count`,
`authorized_candidate_count`, `rerank_candidate_count` (selected prefix),
`rerank_batch_count` (batches attempted, excluding retry attempts), and
`fallback_reason` (null or a sanitized code). Existing `score_type=rank_fusion`
is retained. `final_order` is `cross_encoder` for a fully reranked candidate set,
`cross_encoder_then_rank_fusion` for a reranked prefix, and `rank_fusion` for
fallback or disabled reranking. A `complete` status means every batch in the
selected prefix completed. Dense failures fall back to lexical search. SQL
failures remain errors.

## KnowledgeContext v2

POST `/api/v1/kbs/{kb}/knowledge/context` accepts an authenticated Utopia session
or supported reader PAT, the KB's bound tenant_id, entity name/current UUID,
optional entity_type, at, as_of and limit. KB membership is checked before
tenant lookup. The source/tenant binding is administrator-owned and immutable.

The response contains query/KB/tenant IDs, resolved entities, ledger facts,
versioned source/chunk citations, both temporal axes, methods, conflicts, model
metadata, latency and limitations. SQL limits each entity timeline before
loading evidence. Results are bounded to five entity candidates and 100 facts;
each fact has at most eight eligible evidence references.

For as_of queries, use an entity UUID and omit the current-type filter.
Historical display names/types are not reconstructed from current projections;
the context returns UUID names. Evidence must belong to a document/chunk live at
the requested record time and have been attached by then. New evidence links
have recorded_at; legacy attachment times are unknown and excluded from
historical citations. Missing/contested evidence makes the context partial.
Current queries still expose legacy evidence. Migration 10002 never invents
attachment timestamps for old links.

```bash
python3 -m soorin.ops.context --kb "$UTOPIA_KB_ID" --tenant tenant-blue --entity A1
python3 -m soorin.ops.context --kb "$UTOPIA_KB_ID" --tenant tenant-blue --entity "$ENTITY_UUID" --at 2026-10-20T10:00:00Z --as-of 2026-11-05T10:00:00Z --extractive
```

The extractive answer helper cites only eligible document/chunk/version
references and rejects unsupported prose or contested facts. It certifies exact
ledger statements, not arbitrary generated conclusions. Open-vs-typed alignment
is separate from observed/asserted/inferred security confidence.
The service triggers no response, ticketing, containment or AutoTriage actions.

## Evaluation boundary

`python3 -m soorin.evaluation.retrieval_benchmark` is a reproducible tiny synthetic
contract benchmark (4 documents / 3 queries), not evidence of production quality
or a real BGE improvement. Runtime dense/reranker results require the optional
model smoke commands and native API tests. Record model revisions, hardware,
latency, fallback rate, recall/MRR/nDCG and citations when running a larger held-out
SOC evaluation. External DeepSeek/gateway tests must never be counted as PASS
without actual successful protected calls.

## Final hardening additions

KnowledgeContext returns `bounds` with conservative truncation/has-more metadata,
returned count, candidate lower-bound indicator and explicit limits. Truncation
forces partial status; extractive answers preserve partial status. Each fact's
evidence fetch is SQL-bounded to 65 rows (64 examined plus sentinel), with at most
8 eligible references returned. This can omit later eligible citations when the
first candidates are ineligible; the result remains explicitly partial, not exhaustive.
`model_versions` reports `usage=none` / `deterministic_graph_lookup` because this
endpoint does not invoke embeddings, reranking or an LLM. Search model lineage
remains a separate native retrieval concern.

## V1 baseline update

V1 baseline exposes `lexical_method` additively (retaining `lexical`) and includes retrieval diagnostics in MCP search_chunks structuredContent. Invalid MCP as_of errors instead of searching today. REST search accepts KB-scoped read PATs. UI displays reranker_status=complete as executed. Exact authority lookup is `/knowledge/resolve`; BM25/name similarity is never exact resolution. See [agent contracts](AGENT_TOOL_CONTRACTS.md).


## CPU budgets and timing

On Server 55, a Search with 48 authorized candidates ran for 90.66 seconds
and returned RRF fallback. Its reranker span ended at 90.023 seconds with
`rerank_deadline`. A direct eight-pair POST succeeded. Six sequential POSTs
against a CPU shared with embedding and NER can exceed the aggregate budget.
The incident did not measure separate tokenization, queue, and forward-pass
durations. The patch defaults to 16 candidates in two batches while retaining
48 in first-stage retrieval.

| Runtime setting | Default and valid range | Precedence and scope |
| --- | --- | --- |
| `SOORIN_RERANK_MAX_CANDIDATES` | 16, integer 1–48 | App env, caps the authorized RRF prefix |
| `SOORIN_RERANK_BATCH_SIZE` | 8, integer 1–16 | App env, further split if serialized body would exceed 300,000 bytes |
| `SOORIN_RERANK_TIMEOUT_SECONDS` | 18 s, integer 5–180 | App env, capped by remaining aggregate deadline. Includes HTTP connect, waiting and response reads |
| `SOORIN_RERANK_DEADLINE_SECONDS` | 30 s, integer 5–180 | App env, covers all batches and at most one transient retry |
| `SOORIN_MODEL_QUEUE_CAPACITY` | 4 waiters, integer 0–4 | Unified process. Isolated role env uses `SOORIN_{EMBEDDING,RERANKER,NER}_MODEL_QUEUE_CAPACITY` with defaults 2/1/1 |
| `SOORIN_MODEL_QUEUE_TIMEOUT_SECONDS` | 6 s, positive up to 120 | Unified process. Isolated role defaults 6/3/3 using the role-specific prefix above |
| `SOORIN_MODEL_THREADS` | 2, integer 1–8 | Unified PyTorch thread count. Isolated roles default to 1 via role-specific prefix |
| `UTOPIA_MODEL_READ_SECONDS` | 300 s idle timeout unless overridden, JSON map values 1–3600 | Exact model string overrides the generic client. Search query embedding retains an independent 30 s limit. Reranking uses its own HTTP client |

Invalid app reranker settings use defaults. Invalid model queue or thread
settings fail at startup. Search allows the query-embedding budget plus the
configured reranker deadline and 15 seconds for retrieval overhead after
authorization. That is 75 seconds by default, with no more than 30 spent
reranking and a 3-second reranker connect limit. Use a client timeout above
the Search budget when measuring the app deadline. Acceptance defaults to
80 seconds per probe and an independent 180-second retrieval phase.
Both model revisions and the 512-token model limit are retained. Rust still
clips inputs to 4,000 query characters and 8,000 chunk characters. Changing
the text window further needs evidence of a stable relevance tradeoff.

### Reproduce the comparison

```bash
python3 -m soorin.evaluation.cpu_rerank_benchmark --offline
```

A deterministic three-query fixture over 48 synthetic ranks puts relevant
items at positions 8, 13 and 16. Recall@10, MRR@10 and nDCG@10 are each 0.333
for windows of 8 and 12, and 1.000 for 16, 24 and 48. A padded-token work
model with pair lengths up to 512 estimates 7,376 token positions for 16
pairs and 22,128 for 48. For 16 candidates, outer batches of 4, 8 and 16
require 4, 2 and 1 POSTs respectively. The token proxy is the same because
the installed cross-encoder processes groups of four. This validates the
ranking boundary and models workload only. Real BGE quality, throughput and
latency still require labeled server queries and controlled CPU measurements.

Use the operator-only timing probe on the already running Server 55 model
during a quiet window. It compares outer batches 4/8/16 with 500/1,800/3,500
character synthetic passages and records connection and request times.
Join Rust provider request IDs to the model's `queue_wait_ms` and
`duration_ms` for actual model timings. Request time includes connection
handling, serialization, queueing, and inference. Compare the same corpus
and concurrency in unified and isolated mode.

```bash
python3 -m soorin.evaluation.cpu_rerank_benchmark --existing-server-model --port 2812
```

### Investigate fallback

Filter app logs on `search`, `search.rerank_fallback` and the opaque
`request_id`. Rust emits stage durations for authorization, lexical, dense,
fusion, provider batches, and the final response. Stage success events are
debug level. The model exposes counts and cumulative inference seconds at
`/ready`. Set `SOORIN_MODEL_LOG_LEVEL=DEBUG` temporarily on the new model
image for per-request events with UUIDs, queue and model execution times.
Filter `queue_timeout` for expired provider waits, `provider_http_429` for other
model saturation, `search_capacity` for an unavailable foreground permit,
`provider_timeout` for per-POST expiration, and `rerank_deadline` for aggregate
expiration. HTTP 503, invalid scores and egress rejection have separate
categories. Neither log stream records query text, document text, raw
provider bodies, or credentials. See [Server 55 model rollout](SERVER55_PRODUCTION_RELEASE.md).
