# Model configuration

## Precedence and ownership

```text
disabled/validated application defaults
  -> SOORIN_* environment defaults
  -> authorized Utopia workspace chat/embedding settings
```

Workspace values override only fields they actually contain. Production chat and embedding calls remain in Utopia's Rust `LlmClient`; `soorin/models/` supplies validated profiles, offline fakes, embedding evaluation, and narrow health probes. Reranking has a separate inference contract and is not sent to the embedding endpoint.

The service starts with chat, embedding, and reranking disabled. A missing model is an unavailable optional feature, not a startup failure. Enabling a provider without a valid HTTP(S) base URL and model fails validation explicitly.

## Environment names

- Chat: `SOORIN_CHAT_ENABLED`, `PROVIDER`, `BASE_URL`, `MODEL`, `API_KEY`, `REASONING_EFFORT`, `TIMEOUT_SECONDS`, `RETRIES`, `MAX_CONCURRENCY`, `MAX_OUTPUT_TOKENS`, `STRUCTURED_OUTPUT`, `TLS_VERIFY` under the `SOORIN_CHAT_` prefix.
- Embedding: `SOORIN_EMBED_ENABLED`, `PROVIDER`, `BASE_URL`, `MODEL`, `API_KEY`, `DIM`, `TIMEOUT_SECONDS`, `RETRIES`, `BATCH_SIZE`, `MAX_CONCURRENCY`, `NORMALIZE`, `CACHE_ENABLED` under `SOORIN_EMBED_`.
- Reranker: `SOORIN_RERANK_ENABLED`, `PROVIDER`, `BASE_URL`, `MODEL`, `API_KEY`, `TIMEOUT_SECONDS`, `TOP_N`, `BATCH_SIZE`, `MAX_CONCURRENCY`, `FALLBACK_ENABLED`, `MAX_DOCUMENT_CHARS` under `SOORIN_RERANK_`.

See `soorin/config/soorin.example.env`; it contains no live secrets. `public_dict()` omits key values and returns only `has_api_key`.

## Provider behavior

- Chat: OpenAI-compatible health probe with reasoning effort and bounded output. Utopia owns retries/streaming/tool calls in production.
- Embedding: OpenAI-compatible `/embeddings`, indexed response ordering, batching, bounded retry, optional cache/normalization, finite-value and dimension validation. `BAAI/bge-m3`/1024 is an evaluation candidate, never a hardcoded assumption.
- Reranker: adapters for Cohere v2, Jina v1, and Hugging Face TEI shapes. Response count, indices, scores, IDs, and stable tie order are validated.

No live endpoint was configured or claimed in Sprint 1. Standard tests use deterministic fakes.

## Docker networking and privacy

Inside Docker, `localhost` means the container. For a host model service use an explicitly approved host gateway/DNS name reachable from the container. Do not send production SOC content externally until the deployment's privacy boundary is approved. The semantic text builder excludes raw OCSF envelopes, SPL, macro definitions, and obvious credential fields by default.
