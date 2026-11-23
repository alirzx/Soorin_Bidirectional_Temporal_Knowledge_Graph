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

Native optional TEI reranking scores all eligible candidates in batches <=16,
validates complete unique indices and finite scores, and sorts by raw relevance
score then original candidate order. It retains candidates beyond 16. With
fallback=true, any failed batch preserves the entire original RRF list.
With fallback=false, provider failure is explicit. Relevance is not maliciousness
probability. Reranking cannot introduce candidates.

Search responses include retrieval metadata: dense_executed, lexical method,
reranker_status, candidate_count and returned. Dense failures fall back to
lexical search; SQL failures remain errors. The UI exposes lexical-only and
reranker-fallback state. A nonempty hybrid result alone does not prove dense
inference or reranker execution.

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


## CPU-only reranker diagnostics and safe tuning

The consolidated three-model CPU service shares **one** inference slot (with at
most four queued callers). The initial Rust reranker requested up to 16
candidate pairs per call with a 30-second HTTP timeout. This can be insufficient
on a busy CPU host even if a separate two-candidate model smoke test passed.

The reranking integration now defaults to **8 candidates per batch** and a
**90-second per-request timeout**. Operators can tune these deployment-owned
environment variables on the **app** container only:

- `SOORIN_RERANK_BATCH_SIZE`: integer 1..16, default 8; invalid values use 8.
- `SOORIN_RERANK_TIMEOUT_SECONDS`: integer 5..180, default 90; invalid values use 90.

The values are read when a Search invokes the reranker; no change is made to
the retrieval candidate ceiling (48), KB scope, temporal filters, result format,
or RRF fallback policy. These changes require **building/deploying the new Rust
app image**; merely checking out source does not change a running container.
An application recreation without a rebuilt image cannot apply these Rust
changes. Keep the existing database and cache volumes intact.

A fallback now emits a structured, **sanitized** warning: `reason`,
`candidate_count`, `batch_size`, `timeout_seconds`, `elapsed_ms`.
Known categories include `egress_blocked`, `provider_timeout`,
`provider_connect`, `provider_transport`, `provider_http_<status>`,
`provider_invalid_json`, and `provider_invalid_scores`.
No request content, model URL, provider response body, or credential is logged.
Clients still receive the previous public `reranker_status` values.

Before deployment, diagnose from the current running container:

1. Check app `UTOPIA_MODEL_TRUSTED_ORIGINS` contains the exact model origin
   `http://models:8081`. Do not add external or unapproved destinations.
2. Use the pinned model's `/rerank` contract and time two synthetic batches
   of 2 and 8 candidates directly from inside the app network.
3. Check model `/ready` call counters before and after Search. A static
   reranker counter with fallback often indicates egress/configuration/transport
   failure; an increment suggests the service received at least a request.
4. Finish background embedding/backfill before benchmarking. The shared CPU
   inference gate serializes heavy work and can return 429 under saturation.
5. Verify `reranker_status=complete`, no unauthorized cross-KB results,
   latency and answer relevance on a controlled SOC query set. `fallback`
   remains a degraded but usable RRF result, not a passing reranker test.

Do not start the 5,500-alert acceptance while a model saturation incident is
unresolved. Even after retrieval succeeds, separately verify run-scoped
receipt binding, active vector coverage, identity resolution, temporal
evidence context, tenant isolation, and recovery behavior.
