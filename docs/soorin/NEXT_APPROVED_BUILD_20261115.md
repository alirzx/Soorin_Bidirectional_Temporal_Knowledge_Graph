# Next approved build and acceptance sequence

These commands were **not executed** in the continuation. They are a handoff for
a separately approved build/runtime session. Use existing dependencies/images/
model caches where qualified; stop for missing dependencies rather than silently
installing/downloading. Never delete or relabel an existing QA volume.

1. **Exact existing-QA preflight and backup.** Follow the complete
   [app-only runbook](APP_ONLY_REBUILD_20261115.md), including Compose labels,
   final-SHA green CI, the actual **`.env`**, immutable old image pin, coordinated
   DB/app backup and independent restore verification. Never regenerate the
   password, initialize `.env.qa`, delete historical volumes or modify the old KB.
2. **Migration verification.** Inventory remains 105 unique SQL versions, latest
   10004. Export the existing checksum ledger read only and audit it with
   `python3 -m soorin.ops.migrations --applied-json FILE`. DB-dependent Rust tests
   use independent disposable databases only; see [build checks](BUILD_AND_TEST_HANDOFF.md).
3. **Application build, bounded and once.** After backup/restore qualification:
   `make qa-config QA_ENV_FILE=.env`, then
   `SOORIN_BUILD_JOBS=1 timeout 1800s make qa-build QA_ENV_FILE=.env`. Save the
   exact Git SHA, build log and resulting immutable image ID. Stop on timeout.
4. **App-only replacement.** Use the runbook's `up -d --no-deps --no-build
   --pull never --force-recreate app` with the same `.env` and project. Never use
   `qa-up` for this existing deployment. PostgreSQL and both original volumes
   stay in place. Verify source counts, migration checksums and v3 Tantivy
   recovery before native deterministic and ten-alert acceptance in new KBs.
5. **Model-cache verification.** Build the revised model image separately only
   with approval: `make qa-model-build QA_ENV_FILE=.env`. For each role, mount
   its existing cache read only and run the documented network-none
   `verify-artifacts --role ROLE --cache PATH --hashes` from
   [Artifact management](MODEL_ARTIFACT_MANAGEMENT.md). All three pinned snapshots
   must pass. Missing snapshots are BLOCKED, not an automatic download request.
6. **Model startup / smoke.** `make qa-model-up QA_ENV_FILE=.env QA_EXECUTE=YES`.
   Verify readiness at loopback 2811/2812/2813, then bounded inference probes:

   ```bash
   timeout 120s python3 -m soorin.ops.models smoke --role embedding --base-url http://127.0.0.1:2811
   timeout 120s python3 -m soorin.ops.models smoke --role reranker --base-url http://127.0.0.1:2812
   timeout 120s python3 -m soorin.ops.models smoke --role ner --base-url http://127.0.0.1:2813
   ```

   Record p50/p95, peak RAM, concurrent ontology/document work, 429 retry behavior
   and cache-only restart. No external LLM is part of these probes.
7. **Native SOC E2E.** Use the ownership-gated harness, which creates synthetic
   workspaces/KBs/sources; do not target historical user KBs. If registration is
   already closed, supply a valid `UTOPIA_SESSION_TOKEN` from normal QA login;
   the harness authenticates it and creates a new synthetic workspace. Without
   a session it only works during first-account bootstrap on a fresh disposable
   database. It never enables registration or changes an existing workspace's
   model settings. Deterministic-only first:

   ```bash
   SOORIN_DISPOSABLE_ACCEPTANCE=1 timeout 1800s python3 -m soorin.e2e.native_validation \
     --base-url http://127.0.0.1:2526 --qa-project soorin-tkg-v1-qa --approved-port 2526 \
     --execute --deadline 300 --report /tmp/soorin-native-acceptance.json
   ```

   Repeat in a newly created synthetic test KB using `--with-cpu-models` after
   smoke checks. Equivalent Make target accepts `QA_NATIVE_ARGS=--with-cpu-models`.
   Confirm exact identities/types, relation endpoints, current-version evidence,
   receipt bound, replay deduplication and source authority. Curated preview and
   ingest examples are in [Manual ingestion](MANUAL_SOC_INGESTION.md).
8. **Temporal graph and recovery.** Exercise three concurrent same-source receipts,
   independent sources, pending/failed predecessors, cancellation/120-second lease
   expiry, restart, late/equal source clocks and correction history. Preserve human
   rejected bindings. Inject DB acknowledgement failure and ensure the handler
   is not repeated. Repair one failed document, then retry only its receipt and
   successor; keep previous failed job rows. No mass requeue or graph rebuild.
9. **Retrieval verification.** Require dense execution, Tantivy BM25 and completed
   reranking separately from measured relevance. Use the versioned bilingual
   acceptance fixture plus a real relevance set; save Recall@K/MRR/nDCG, temporal/
   tenant filtering, exact-ID rank and citation completeness. Evaluate long BGE
   centroids and 512-token coverage. NER proposals must remain review only; measure
   precision/recall/false positives/latency/RAM without granting authority.
10. **MCP.** Obtain a scoped **read PAT** through normal admin/UI provisioning.
    On the intended synthetic KB, POST `/api/v1/kbs/$KB_ID/mcp` with
    `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, then
    `tools/call` for `find_entities` with known synthetic input. Expect eleven read
    tools. Verify revoked token 401, wrong KB denial, invalid arguments/unknown tool
    error shape and absence of write tools. Do not use source ingest credentials.
11. **Privacy / Chat / native Agent.** Configure actual approved endpoint/model,
    key environment variable, reasoning and idle timeout with `soorin.ops.models
    configure --chat`. Populate the canonical workspace→tenant map and Gateway
    allowlist/service key out of Git. Test synthetic create/encode/provider/decode/
    cleanup, timeouts/cancellation, no raw fallback and no secret logging. Then
    test native agent tools, budgets, grounded citations, persistence, malformed
    replies, streaming semantics and denied tool calls. This does not prove live
    Agentic_SOC investigation integration.
12. **Final release acceptance.** Record exact Git/image hashes, commands, logs,
    skips, duration, metrics, backup/restore and rollback evidence. Distinguish
    SOURCE_PATCH_COMPLETE / READY_FOR_NEXT_LOCAL_BUILD from FULL_E2E_VERIFIED.
    Production is unqualified until every required runtime gate passes.
