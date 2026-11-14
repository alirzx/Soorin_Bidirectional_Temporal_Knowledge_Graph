# Model artifact lifecycle

Five distinct stages must be reported separately: metadata verification, artifact
download, artifact integrity, model loading, and inference. Only the first three
are permitted in the current engineering phase. No real model was loaded or
executed during this pass.

Pins are in `soorin/services/cpu_models.py`: BGE-M3 `5617a9f...`, reranker
`953dc6f...`, NER `1ad52f1...`; full revisions appear in
[Model configuration](MODEL_CONFIGURATION.md). Never substitute a moving branch
for a pinned snapshot.

Commands:

- `download --role ROLE --cache PATH`: obtains pinned repository metadata,
  resumes selected cached files, writes a model/revision/file-size/checksum
  manifest. It imports Hugging Face Hub only, never PyTorch or a model loader.
  Safetensors are preferred over duplicate PyTorch weights when available.
- `verify-artifacts --role ROLE --cache PATH [--hashes]`: offline filesystem-only
  inspection. Checks the expected snapshot, manifest identity, required config,
  tokenizer and weights, file coverage/sizes and optional SHA256/git-blob hashes.
- `serve --role ROLE`: legacy isolated single-role launcher.
- `serve-all --cache /models`: deployment command; integrity-verifies and loads
  embedding, reranker and NER from `/models/<role>` **before opening ports**
  8080/8081/8082. Each snapshot is a separate read-only volume. The three
  listeners share one process and one bounded inference slot. Never use it as an artifact inspection command.
- Legacy `init` is retained as a **download-only** alias. It no longer establishes
  model/dependency compatibility or inference readiness.

Example artifact preparation for the next authorized window (image must already
exist; no build or inference is implicit):

```bash
# Set SOORIN_MODEL_IMAGE to a reviewed existing image, ROLE to one of
# embedding/reranker/ner, and SOORIN_MODEL_CACHE_VOLUME to that role's cache.
docker run --rm --pull never --user 0 --entrypoint timeout \
  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  -v "$SOORIN_MODEL_CACHE_VOLUME:/models" "$SOORIN_MODEL_IMAGE" \
  --signal=INT --kill-after=10s 120s python -m soorin.services.cpu_models \
  download --role "$ROLE" --cache /models

docker run --rm --pull never --network none --read-only --user 65532:65532 \
  --entrypoint timeout -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$SOORIN_MODEL_CACHE_VOLUME:/models:ro" "$SOORIN_MODEL_IMAGE" \
  60s python -m soorin.services.cpu_models verify-artifacts --role "$ROLE" --hashes
```

Stop after the deadline. Preserve `.incomplete` blobs and snapshots; resume the
same cache in a later bounded window. Missing weights/files report
`MODEL_ARTIFACT_DOWNLOAD_INCOMPLETE`; a manifest/checksum gap reports
`ARTIFACT_VERIFICATION_INCOMPLETE`. Neither is failed inference. A file inventory
without a trusted manifest is not verified integrity. No redownload of complete
artifacts is needed to add metadata: Hub's cache-aware download reuses them.

Cache writers run explicitly with write access. Production serving is UID/GID
65532 with read-only mounts and offline environment. Ensure directories and files
are readable by that UID; do not use world-writable permissions. Compose prefixes
cache volumes with its project name; validation caches are separate. Never prune
or remove a cache as a startup repair.

## Consolidated QA deployment (one image, one container)

Use `make qa-model-build`, then `make qa-model-create`. Compose creates
three independent named volumes: `soorin-tkg-v1-qa_soorin_embedding_cache`,
`soorin-tkg-v1-qa_soorin_reranker_cache`, and
`soorin-tkg-v1-qa_soorin_ner_cache`. Model download must mount each volume
**writable** at `/models` in a temporary `docker run` and pass
`--cache /models`; never write to the read-only serving mounts.

```bash
# Replace ROLE with embedding, reranker or ner, one role at a time.
ROLE=embedding
VOLUME="soorin-tkg-v1-qa_soorin_${ROLE}_cache"
IMAGE=soorin-tkg-v1-qa-models:latest
timeout 1800s docker run --rm --pull never --user 0 --entrypoint python \
  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  -v "$VOLUME:/models" "$IMAGE" -m soorin.services.cpu_models \
  download --role "$ROLE" --cache /models
docker run --rm --pull never --network none --read-only --user 65532:65532 \
  --entrypoint python -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$VOLUME:/models:ro" "$IMAGE" -m soorin.services.cpu_models \
  verify-artifacts --role "$ROLE" --cache /models --hashes
```

Repeat for **all three** roles and require three PASS reports before
`make qa-model-up QA_EXECUTE=YES`. One missing cache blocks the unified service.
Do not delete the existing `soorin-tkg-v1-qa-embedding` image or legacy
caches to make this work. The model container has no access to TKG DB volumes.

## Slow Hugging Face CDN and terminal disconnect recovery

The model image pins `hf-xet==1.7.1` alongside `huggingface-hub==0.30.2`
and uses bounded `HF_HUB_DOWNLOAD_TIMEOUT=120`,
`HF_HUB_ETAG_TIMEOUT=30`, `SOORIN_HF_RETRIES=3`. Download and verify
operations remain **separate from offline model serving**. Xet can transfer
chunks more efficiently when its storage endpoints are reachable. Setting
`HF_XET_HIGH_PERFORMANCE=1` increases resource usage and is not a default
for constrained CPU hosts. If Xet itself fails due to DNS/TLS or a blocked
endpoint, pass `HF_HUB_DISABLE_XET=1` only to the download container
to use the regular HTTP fallback. Liara/Chabokan mirror *Python packages*,
not model weights on Hugging Face storage/CDN.

The downloader resumes the same pinned cache and allows only transient
network failures to trigger application-level retries. Existing completed
blobs and `.incomplete` files must not be manually deleted. Missing or bad
model revisions, authentication failures and malformed metadata are not
retried as connection timeouts.

For downloads likely to outlive a terminal session, use a **tmux session**
on the host and keep each role independent:

```bash
tmux new -s soorin-model-download
cd /mnt/X/Soorin/soorin_bi_TKG/utopia
ROLE=reranker
MODEL_IMAGE=soorin-tkg-v1-qa-models:latest
VOLUME="soorin-tkg-v1-qa_soorin_${ROLE}_cache"
set -o pipefail
timeout --signal=INT --kill-after=20s 3600s docker run --rm \
  --pull never --user 0 --entrypoint python \
  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  -e HF_HUB_DOWNLOAD_TIMEOUT=120 -e HF_HUB_ETAG_TIMEOUT=30 \
  -e SOORIN_HF_RETRIES=3 \
  -v "$VOLUME:/models" "$MODEL_IMAGE" \
  -m soorin.services.cpu_models download --role "$ROLE" --cache /models \
  2>&1 | tee "/tmp/soorin-${ROLE}-download.log"
```

Detach with `Ctrl+b`, then `d`, and reattach using
`tmux attach -t soorin-model-download`. If a transfer is interrupted,
rerun the exact same role and volume command to resume; do not launch
two writers concurrently against the same cache. The log contains transfer
details and may include diagnostic URLs: keep it local and sanitized.

Only after a successful download, run the **offline** `verify-artifacts
--hashes` on that role's cache. Download-time `PASS` with
`hashes_checked=false` is not a full hash verification. Do not start the
unified `models` container until all three cache verifications pass.

## Observed during this pass

`soorin_master_embedding_cache` and `soorin_master_ner_cache` contain required
snapshot files, no `.incomplete` blob was found, and neither has the new manifest.
Therefore integrity is unverified. The earlier interrupted BGE download has
present weight files now; this is not evidence of successful loading or inference.
No reranker cache volume was present in the inspected inventory. No artifacts were
downloaded, modified or deleted in this pass. Model image rebuild, offline load,
real inference and resource measurements are deferred.

## V1 baseline update

This V1 baseline pass did not inventory or alter existing model volumes and did not download/load/serve/infer. Earlier cache findings are historical, not current readiness proof. Compose volume names default to `<project>_soorin_embedding_cache`, `_soorin_reranker_cache`, `_soorin_ner_cache`; a new QA project does not automatically reuse soorin_master caches. In the future phase explicitly verify manifests, pinned revisions, UID 65532 read permission and chosen cache ownership before offline serving. Do not copy or rename existing caches implicitly.
