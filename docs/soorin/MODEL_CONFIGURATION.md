# Native model deployment and CPU acceptance

The Rust server reads authenticated **Workspace Settings** for Chat and
Embedding. Python `SOORIN_*` evaluation variables do not configure that server.
Reranking uses the administrator-only workspace runtime API. Optional model
profiles do not affect basic application health or deterministic SOC alignment.

| Role | Pinned model revision | Native endpoint | Cache volume suffix |
| --- | --- | --- | --- |
| embedding | BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181 | http://embedding:8080/v1 | soorin_embedding_cache |
| reranker | BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e | http://reranker:8080 | soorin_reranker_cache |
| NER | bnsapa/cybersecurity-ner@1ad52f1a7686a58da2a427c0706d8b868df47181 | http://ner:8080/ner | soorin_ner_cache |

Compose prefixes volumes with the project name. These are separate from the
validation-only `soorin_master_*` caches. Never delete caches to repair startup.

## Download once, then start offline

Run one profile at a time on a constrained host. Each profile has 2 CPUs, a
4 GiB memory limit, one inference slot, batches <=16, and bounded request text.
The runtime user is 65532. Initialization deliberately uses root to populate
the initially root-owned named volume; cached runtime reads it without writes.

```bash
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml -f docker-compose.models.yml --profile ner build ner
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml -f docker-compose.models.yml --profile ner run --rm --no-deps --user 0 -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 ner init --role ner
docker compose -p soorin-sprint1 -f docker-compose.soorin-dev.yml -f docker-compose.models.yml --profile ner up -d ner
python3 -m soorin.ops.models smoke --role ner --base-url http://127.0.0.1:2813
```

Replace `ner` with `embedding` (port 2811) or `reranker` (2812) for the other
roles, including the profile, service and `--role` arguments. Model startup
sets HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1. A missing pinned snapshot
fails readiness; startup never downloads weights implicitly. Repeating the
explicit init command resumes an interrupted download from the same cache.
No runtime needs GPU, CUDA, or a model-provider API key.

Embedding and reranking inspect the first 512 tokens, with input bounded by
16,000 characters. Native reranking additionally bounds query/text to 4,000 /
8,000 characters. NER inspects the first 4,000 characters / 512 tokens, supports
English, and returns no English-model proposals for Persian/Arabic script.
BGE's multilingual input support is distinct from this English NER restriction.
Truncation and NER scores do not establish security confidence.

## Configure the native server

Obtain a workspace administrator session using the normal Utopia login/UI.
Supply UTOPIA_SESSION_TOKEN in the shell; never put credentials in Git or CLI
arguments. The helper fetches existing nonsecret settings before updating them.

```bash
python3 -m soorin.ops.models configure --workspace "$UTOPIA_WORKSPACE_ID" --embedding --reranker
# Also supply DEEPSEEK_API_KEY securely, then:
python3 -m soorin.ops.models configure --workspace "$UTOPIA_WORKSPACE_ID" --chat
```

Chat defaults to `https://api.deepseek.com`, model `deepseek-flash`, and
`chat_reasoning_effort=none`, translated to `thinking: {type: disabled}`.
Set DEEPSEEK_MODEL explicitly when the provider account requires another model.
Model aliases are provider-controlled, so a successful settings write is not a
connectivity test. Use Workspace Settings' authenticated connection test
(`POST /api/v1/workspaces/{id}/settings/test`) with synthetic input.

A remote Chat endpoint remains **blocked** until the gateway deployment
configuration in [Outbound privacy](OUTBOUND_PRIVACY.md) is complete. Do not add
an external provider to UTOPIA_MODEL_TRUSTED_ORIGINS to bypass that boundary.

Reranker settings are GET/PUT `/api/v1/workspaces/{id}/settings/reranker`.
The request is `{enabled,base_url,model,fallback}`; fallback defaults false.
Only trusted internal origins are supported for reranking. The Search UI reports
lexical-only retrieval and explicit reranker fallback.

## Embedding lineage and recovery

Document vectors carry a SHA256 fingerprint of endpoint, model revision/name
and configured dimension. Unknown legacy vectors and other fingerprints are
excluded from dense search. In-flight writes lock/check the current settings.
The per-turn query cache includes workspace UUID, fingerprint and exact text;
only finite, dimension-compatible successful vectors can enter it.

After changing model settings, POST
`/api/v1/workspaces/{id}/settings/embedding/backfill` as workspace admin.
The response queues at most 1,000 documents using the existing durable job
queue. Repeat until zero; inspect `soc_reembed_document` failures in Jobs.
Current live chunks are backfilled; superseded chunks remain lexical/graph
history and are not silently re-embedded or matched to incompatible vectors.

Read [Final acceptance](FINAL_ACCEPTANCE_REPORT.md) for actual model download,
inference, cache restart, memory and latency results. Fake-model contract tests
are not real-model acceptance.
