# Final engineering register — 2026-11-05

Starting tree: `585a03466147616bd271a59225b5ff5757014f05`, clean feature branch.
Historical M01–M10 work is preserved in commits through that baseline. This pass
reviewed the changes since `b6162c4` and made the following corrections.

| ID / severity | Root cause | Correction and evidence |
|---|---|---|
| A01 / CI blocker | Three Rust files were not formatted; Clippy was skipped | Dedicated `7a2cb7c`; bounded rustfmt and offline metadata PASS |
| A02 / high | `initialize()` downloaded then loaded weights | `20f9e6b`; download/verify/serve separated, manifest/file/hash checks, fake tests; no real load |
| A03 / high | Receipt creation order confused delivery with source revisions | `9598b81`; compare source observed clock, quarantine older/equal changed content; DB acceptance pending |
| A04 / high | Fact renderer relabeled analyst assertions observed | Preserve fact confidence category; Rust regression added, execution pending |
| A05 / high | Raw vendor extensions and excerpts could be retained by default | Minimize before canonical checksum; native storage policy and explicit deployment exception; Python tests PASS |
| A06 / high | Open document graph completion could be called bound before typed SOC relations | Check recognized relation materialization and source evidence before bound; real pipeline acceptance pending |
| A07 / high | Context caps were invisible and evidence SQL unbounded | Bounds metadata, partial propagation, SQL evidence cap and historical metadata suppression; Python PASS, new Rust/DB tests pending |
| A08 / critical | HTTP construction failure fell back to unrestricted default client; runtime test env bypass available in release | `19c0a7b`; fail closed and compile-time debug/test restriction; Rust execution deferred |
| A09 / high | Generic Compose selected an upstream image; app ran as root; role password interpolated into SQL | `e6603ec`; explicit Soorin production image, non-root app, private networks, role separation and quoted psql variables; static Compose/shell checks PASS |
| A10 / high | Release could publish without exact-commit complete CI | Backend includes migrations/web; release checks latest exact-commit CI and protected environment; operator environment policy still required |
| A11 / medium | No provider-independent native client; context CLI depended on E2E utility | `d15e322`; authenticated bounded no-redirect client, structured redacted errors, mock tests PASS |
| A12 / medium | Runtime role inherited migration-ledger permissions; receipt listing lacked KB-order index | New additive 10003; revoke SQLx ledger access, add KB/created index; migration execution deferred |

## Remaining gates and explicit limits

- Final Rust compile/Clippy/workspace tests/release build are NOT RUN locally in
  this pass. New push CI could not be observed through the available PR-only
  connector; direct API access timed out. Verify final SHA CI before release.
- Fresh/0112 upgrade and runtime role/migration 10003 acceptance are NOT RUN.
  Existing migrations were not altered. Upstream 0111 collision remains BLOCKED
  for upstream combination; no main/upstream merge occurred.
- Source clock ordering is conservative: opaque IDs do not establish order and
  equal clocks require review. Quarantined old observations are durable receipts,
  not automatically imported historical graph revisions. There is no automatic
  quarantine resolution or retraction admission workflow.
- Registration is resumable across transactions, not atomic with asynchronous
  materialization. Crash, lease expiry, identity conflict and operator recovery
  need live fault-injection tests. Large recognized-relation batches perform
  bounded per-relation DB checks; throughput remains unmeasured.
- Context bounds deliberately allow partial results; no pagination/cursor or
  exhaustive count is promised. Historical current labels are withheld. Legacy
  evidence lacks trustworthy attachment time and remains excluded historically.
- Structural minimization is not semantic DLP. Retention jobs, encrypted storage,
  network policy, secret rotation, first-admin bootstrap isolation and backup-role
  provisioning remain deployment responsibilities.
- Model artifacts exist for BGE-M3/NER but lack integrity manifests; reranker cache
  was absent. No image rebuild, download, model loading/inference or measurements
  occurred here. Optional model APIs rely on private networks; shared network
  authentication needs further integration (native reranker has no bearer setting).
- The app retains migration-owner credentials for vector-index DDL even with a
  separate runtime role. Further separation requires a reviewed DDL service/job.
- Live Privacy Gateway/DeepSeek and Agentic_SOC integration are NOT RUN. Routine
  mocks prove protocol behavior, not live policy/DLP effectiveness or model quality.
- Production source/runtime image build, base-image and dependency supply-chain
  review, startup, restart/restore, TLS, and deployment acceptance remain NOT RUN.

See [Final acceptance](FINAL_ACCEPTANCE_REPORT.md) and
[Build and test handoff](BUILD_AND_TEST_HANDOFF.md). None of these gaps is hidden
by a successful mock test or a previous-commit CI result.
