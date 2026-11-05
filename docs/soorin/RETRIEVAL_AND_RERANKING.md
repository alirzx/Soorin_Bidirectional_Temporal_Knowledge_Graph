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
