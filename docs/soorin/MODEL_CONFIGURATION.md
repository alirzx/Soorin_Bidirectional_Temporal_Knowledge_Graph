# Model configuration · Runtime versus evaluation

> **Sprint 1 readiness:** Chat, embedding, and reranker profiles are implemented and offline-tested. The `SOORIN_*` variables below are currently consumed by **Python Soorin modules**, **not automatically by the upstream Rust server**. No live provider has been validated.

## Production runtime: Utopia Workspace Settings

The running Utopia Rust API persists Chat and Embedding settings through its **authenticated Workspace Settings UI/API**. The supported runtime fields are `chat_base_url`, `chat_model`, `chat_api_key`, `chat_reasoning_effort`, `embed_base_url`, `embed_model`, `embed_api_key`, `embed_dim`. See `crates/utopia-server/src/api/settings_routes.rs`.

Use the Workspace Settings **connection test**, then inspect `align_types` and `embed_ontology` jobs. The service appends `/chat/completions` or `/embeddings` to the configured OpenAI-compatible base URL. Never enter the full endpoint as the base URL.

**Important:** Merely adding `SOORIN_CHAT_ENABLED=true` or `SOORIN_EMBED_ENABLED=true` to a Compose `.env` **does not configure Utopia's live model clients**. The existing `docker-compose.soorin-dev.yml` does not wire those variables into Rust. Do not claim runtime activation from Python profile checks alone.

## Python model evaluation profiles

`soorin/config/soorin.example.env` documents Python-only, optional configuration:

| Prefix | Feature | Runtime integration |
| --- | --- | --- |
| `SOORIN_CHAT_*` | OpenAI-compatible chat readiness probe | **Not** a replacement for Utopia Workspace Settings |
| `SOORIN_EMBED_*` | Embedding client, batching, dimension validation, optional cache | Used by Python test/evaluation components; **not** native Rust vector indexing |
| `SOORIN_RERANK_*` | Cohere v2 / Jina v1 / TEI reranker adapter | Offline Python adapter only; **not wired into Rust search or UI** |

Profiles default to disabled; no secrets, live URLs or provider access are included in Git. `BAAI/bge-m3` with 1024-dimensional dense vectors is an **evaluation candidate**, not an installed/validated service.

Configuration precedence `environment defaults → authorized workspace overrides` exists in the Python `SoorinModelConfig.with_workspace()` adapter **only**. It is not a general precedence rule implemented inside Utopia's production Rust process.

## Model acceptance checklist

1. Verify exact provider URL, provider-specific model ID, TLS and credentials using approved secret storage; never commit tokens.
2. Set **Chat and Embedding** in Utopia Workspace Settings; run its authenticated connectivity test.
3. Validate the actual returned embedding vector length against `embed_dim`; check embedding model migrations/reindex behavior before changing dimensions.
4. Verify Ontology Alignment and indexed/vector search using an **isolated test KB** and real API results.
5. Keep reranking **disabled** until it is connected to native retrieval, protected by authentication and tenant scope, and benchmarked.
6. For remote embeddings, enforce the approved privacy boundary. Removing obvious secret *keys* does not remove sensitive IPs, usernames, hostnames or identifiers embedded within free text.

## Python configuration and example file

The exact example variables are maintained at [`soorin/config/soorin.example.env`](../../soorin/config/soorin.example.env). Never print or paste actual API secrets into logs or documentation.

Inside Docker, `localhost` addresses the **container**. Use an approved reachable network address for host-model services; do not expose inference endpoints publicly by accident.

For offline unit tests, see [Testing and evaluation](TESTING_AND_EVALUATION.md). Live provider verification was **not** performed during Sprint 1.