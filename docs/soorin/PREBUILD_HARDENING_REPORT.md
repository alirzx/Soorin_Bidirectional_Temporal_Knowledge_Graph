# Final pre-build hardening — baseline 84a92bc

This report records source/static work and the subsequently verified exact-head CI
and integration checkpoint. Final feature ref publication/cleanup is reported at
delivery. Production runtime qualification remains a separate phase.

## Repository and preserved state

Repository root: `/mnt/X/Soorin/soorin_bi_TKG/utopia`.
Starting branch: `hardening/prebuild-small-fixes`.
Starting SHA: `84a92bcef479ec784973b66580a297fa57045e3b`.
Both feature refs and local feature branch matched that baseline. The only initial
untracked file was the user-supplied 674×230 company logo, now included as a source
asset and an identical bundled frontend asset. Main is unchanged at
`4bf6a2cb5b98919fe910ba43da7698f7d1b670b9`.

Existing containers were not stopped/restarted/recreated. No model was downloaded,
initialized or executed. No application image/full application build, new stack,
live backfill, local database migration or production deployment was run. Standard remote CI
subsequently exercised its disposable migration/test database. Tool-only
ephemeral containers used cached Rust tooling; the stopped older formatter
container was read only to copy executables. Agentic_SOC and other projects were
not modified. No new SQL migration, ontology change or canonical key change was made.

## Audit and corrections

| Issue / classification | Current behavior and root cause | Existing mitigation / regression risk | Correction / evidence |
|---|---|---|---|
| Unknown relations / confirmed defect | Admission accepted unknown relation strings; materialization skipped them before bound | Existing reviewed vocabulary and quarantine; risk of silent completion | `a2b6a8e`: reject at admission, quarantine incompatible older queued events; Python tests PASS, Rust/API regressions prepared |
| Domain/range and ticket subject / confirmed defect | Notable→ticket did not match reviewed `tracked_by_ticket` domain | Ontology unchanged; strict validation alone would break valid producer scenarios | Route through explicit case/alert, retain unmappable ticket with warning; existing fixture corpora pass native signatures |
| Correlation confidence / confirmed defect | Normalizer assigned observed to correlation/MITRE metadata | Runtime already distinguishes observed/asserted and rejects unreviewed proposals | Preserve attributed assertions; direct confidence regression |
| Source revision clock / confirmed defect | Unchanged occurrence/alert clock could quarantine later source updates | Conservative Rust ordering already correct; opaque revision IDs remain unordered | Prefer explicit source update timestamp without changing event time/checksum algorithm; four-revision regression and delivery-only characterization |
| Provisional identity / missing coverage and compatibility limit | V1 provisional keys omit source namespace; resolver never grants authority from aliases | Immutable native KB source binding; registry requires authority; legacy Statements remains a separate risk | `3896d31`: characterize cross-source collision, tenant/network/authority distinction, aliases; prepared API rebinding 409 regression; no breaking key rewrite |
| Historical evidence / already fixed | Attachment record time and document eligibility restrict old snapshots | Existing later-evidence and pre-entity tests; execution requires DB | Preserved existing temporal tests and semantics; full runtime acceptance deferred |
| Tantivy reload / confirmed upstream defect | Default automatic reader reload can race explicit reload after commit | Single writer mutex already serializes commits | `c678740`: manual policy; concurrency/replacement/delete regression; local test deadline reached before execution |
| rustls patch / suitable dependency update | Lock used 0.23.45 | Existing compatible dependency graph | `87e8166`: precise Cargo offline update to 0.23.46; locked metadata PASS |
| Branding / product inconsistency | Header/login/title/links still identified upstream product; fixed-width tabs overflow | Existing top-header/tab design preserved | `92fb942`: local aspect-preserving artwork, Soorin identity/favicon, scrollable tabs, bounded account/KB labels, accessible login/focus states |
| Existing transport/storage/deployment fixes / already fixed | Fail-closed model transport, minimization, separate production image and role config already present | Must not duplicate or redesign infrastructure | Observational recheck only; Compose static checks preserved |

Native event/profile admission is stricter only for demonstrated invalid relation
signatures/provenance. The general canonical contract/checksum versions remain
unchanged. Newly normalized projections can legitimately change content checksums
when assertions/ticket targets/source clocks are corrected; retries must reuse
the same serialized accepted event. No existing receipt/history is rewritten.

## Selective upstream review

| Upstream | Decision | Soorin commit / validation |
|---|---|---|
| `7baecc9d2a15a676729b3c54e24f62f5fdb0691b` | Applied: manual reader reload | `c678740`; format PASS, test execution NOT RUN after 45s compile deadline |
| `7280c0309fa848bb400362b71bf09d5cb3a7d314` | Applied: rustls 0.23.46 | `87e8166`; registry-resolved checksum, precise offline update, locked metadata PASS |
| `4fec6cb5108895288405e1ffdabae63b76579f3a` | Deferred: optional Vite update | Upstream lock includes broad Rollup changes; local pnpm unavailable; no dependency installation |
| `6466a5e`, `f0b31b1` | Deferred: source search / pagination metadata | Broad retrieval/API/authorization changes |
| `f879b45`, `fbe13bd`, `beb65fc` | Deferred: temporal rewrite / identity evidence / typed conflict governance | DB semantics and migrations require dedicated reconciliation |
| `04376a2`, `3b09f9f` | Deferred: restore protections / identity merge review | Larger CLI/governance qualification surface |

Upstream main/dev refs inspected were `4fec6cb5108895288405e1ffdabae63b76579f3a`
and `f879b45f7f1272db138c6f4e641d004243dc4ba3`. No unrelated-history merge or
upstream migration import occurred. See [Upstream tracking](upstream-sync.md).

## Frontend and product presentation

The supplied image remains 674×230 and unchanged (110,465 bytes). CSS controls its
header/hero width, automatic height, intrinsic ratio and mobile bounds. Its own
navy panel preserves the artwork in both themes. Header navigation scrolls
horizontally; compact screens hide secondary header text while preserving menus.
Login inputs now have accessible names/autocomplete and error alerts. Existing
Graph/Search/Ask/Library/Review/Ontology/Mappings/Settings routes remain intact.

Node tools ran directly from installed dependencies because host pnpm was absent.
Type checking, tests, style guard and the frontend asset build passed. No browser,
mobile screenshot, screen-reader or light/dark visual acceptance is claimed.
The existing large-JavaScript-chunk build warning remains; no broad bundle refactor
was introduced. No new backend endpoint was added for branding.

The README now presents product value, actual architecture/lifecycle diagrams,
components, integration/security/temporal boundaries, deployment, model lifecycle,
acceptance and contribution guidance. Upstream attribution/LICENSE remain. It
links the original upstream demonstration explicitly as Utopia footage; no video
was copied. Direct HEAD verification was BLOCKED by HTTPS connection timeout.
No independent redistribution right for the footage is asserted.

## Validation matrix

| Check | Status / scope |
|---|---|
| Rust format and locked offline metadata | PASS; cached tool-only container, explicit deadlines |
| Python compileall | PASS |
| Python deterministic/mock suite | PASS; 144 tests, no real models |
| Synthetic Splunk suite | PASS; 7 tests |
| Graph integrity and migration inventory | PASS; no fixture failures, 104 migrations, no new migration |
| Frontend tests | PASS; 37 files / 270 tests |
| TypeScript / style guard / frontend assets | PASS; installed tools only |
| Development/production/model Compose | PASS; static placeholders only |
| Git whitespace / local links | PASS; 113 local Markdown links resolve |
| Search Rust unit execution | NOT RUN; 45s deadline during cached dependency compilation, not restarted |
| Server/DB affected regressions | NOT RUN locally; prepared for CI/disposable-DB qualification |
| Exact pushed branch CI | Pending verification after publication; a successful check on another SHA is insufficient |
| Visual/browser acceptance | NOT RUN |
| Video availability | BLOCKED; HTTPS timeout |
| Full Rust/application image build, migrations, real model inference, SOC live E2E, deployment | NOT RUN by task restrictions |

A first tool mount invoked the formatter incorrectly; corrected executable paths
passed formatting. No assertions were weakened. Rust test timeout is not a pass.
The first remote CI run (`42094002467`, head `1df866a`) passed Rust build,
formatting, Clippy, workspace tests, Python and migrations, but caught a missing shared
`ArrowUpRight` icon import after branding. The import was restored; direct local
TypeScript execution passed after the correction. The corrected head must pass
CI before feature integration; the earlier frontend failure is not treated as green.
Logs/reports are local temporary artifacts, excluded from Git.

Graphify's bounded AST-only refresh completed with 12,051 nodes, 31,925 edges
and 607 communities. Its files remain ignored/local-only; these are repository
code-graph counts, not live SOC data. Mermaid diagrams were reviewed structurally;
no browser rendering or unavailable Mermaid parser execution is claimed.

## Git integration and cleanup gates

Push hardening to the personal remote for review/CI. Merge only after exact-SHA
CI is verified successful and both feature refs still match the intended baseline.
Use the requested `--no-ff` checkpoint, rerun lightweight checks, push both feature
remotes and verify via `ls-remote`. If CI cannot be verified, preserve hardening
and leave feature refs untouched; report the blocker.

Preserve `main`. Preserve `utopia-main-backup`: comparison against the feature
history shows unique upstream commits and no shared merge base. Remove local
hardening only after the merge and both pushes are confirmed; never delete remote
branches automatically. A blocker is a reason to retain recovery branches.

Next runtime commands and criteria remain in
[Build and test handoff](BUILD_AND_TEST_HANDOFF.md). Production readiness remains
unverified regardless of static or unit-test results.

## Verified integration checkpoint

The corrected review head `c59d2bff75b874a77f4553790079253913c29223` passed
[CI run 42094917185](https://github.com/alirzx/Soorin_Bidirectional_Temporal_Knowledge_Graph/actions/runs/42094917185):
formatting, Clippy, Rust workspace build/tests, Python, web, migrations and backend
aggregate all succeeded. Rust logs report 1,516 passed, zero failed and six existing
ignored tests across 44 result summaries. The ignored tests are not passes. The
previous local search-test timeout was superseded by its successful remote test
execution; no local compilation loop was used.

Both feature refs were refreshed and still matched the expected `84a92bc` baseline.
The requested non-fast-forward integration created merge
`3ebfe58224b64348f31e381e4d305ee63f10df30`, with the feature baseline and validated
hardening head as its two parents. Its tree exactly matched the validated hardening
head. This final evidence update changes documentation only. Fresh feature-push
CI is distinct from the successful review-head run and must be reported with its
actual observed status at delivery.

PRE-BUILD HARDENING: PASS

READY FOR ISOLATED BUILD: YES

PRODUCTION READY: NOT YET VERIFIED
