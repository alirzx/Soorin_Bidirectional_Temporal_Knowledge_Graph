# Upstream synchronization with clean Soorin history

The Soorin `main` branch starts with an independent root commit based on Utopia `v0.1.0-rc9`; importing Utopia's old Git commits into Soorin is intentional **not** part of this workflow.

Remotes:

- `personal`: `git@github.com:alirzx/Soorin_Bidirectional_Temporal_Knowledge_Graph.git`
- `upstream`: `https://github.com/deeplethe/utopia.git`
- `origin`: `https://github.com/SoorinSecurity/Soorin_Bidirectional_Temporal_Knowledge_Graph`

`origin` is now the Soorin organization repository. Push feature branches to
`personal` and `origin` explicitly. Never push Soorin work to `upstream`.

A normal `git merge upstream/main` would attempt to join unrelated histories and should be avoided. Instead:

1. Record the last upstream revision integrated (initially tag `v0.1.0-rc9`).
2. `git fetch upstream --tags`.
3. Create a Soorin feature branch from `main`.
4. Review `git diff v0.1.0-rc9 upstream/main -- crates/ migrations/ web/ ...` for the **first** sync, or diff from the new recorded upstream baseline on subsequent syncs.
5. Apply only reviewed patches in the feature branch. Resolve conflicts, migrate schemas intentionally, run Rust/UI regression and SOC mock tests.
6. Commit **as Soorin commits** and merge a reviewed PR. Update the recorded upstream baseline tag/SHA.

`git diff ... | git apply --3way` is a possible starting point for carefully scoped paths, but **not** a blanket command when local modifications exist. In particular, exclude/inspect `README.md`, `.gitignore`, local Compose overrides, `docs/soorin/`, and `soorin/`.

License attribution remains required regardless of clean Git commit ancestry.

## Migration 0111 collision — current release blocker for upstream combination

Soorin `0111_soorin_external_identity_registry.sql` and upstream
`0111_an_uploaded_original_has_a_version.sql` have different SQLx checksums.
Run `timeout 15s python3 -m soorin.ops.migrations --upstream-ref upstream/main`;
a nonzero result is expected until reconciliation. It is not a failed Soorin
fresh-schema migration test. The current Soorin tree has 104 migrations.

Do not rename/delete/edit applied 0111/0112 or change `_sqlx_migrations` to pretend
the two histories match. Reconciliation must be a separately reviewed roll-forward
plan: inventory deployed schema/checksum histories, isolate upstream schema effects,
translate required changes into new uniquely numbered Soorin migrations, review
upstream source assumptions, and test fresh installs plus upgrades from every
supported history on disposable copies. Maintain a mapping from upstream changes
to translated migration IDs. Preserve the deployed checksums and back up before
any rollout. No upstream merge or reconciliation execution occurred in this pass.

## Selective pre-build review — baseline 84a92bc

Audited upstream refs: main `4fec6cb5108895288405e1ffdabae63b76579f3a`, dev
`f879b45f7f1272db138c6f4e641d004243dc4ba3`. SSH fetch refreshed the upstream
references; HTTPS authentication was unavailable. No upstream merge occurred.

| Upstream commit | Decision / Soorin adaptation | Evidence |
|---|---|---|
| `7baecc9d2a15a676729b3c54e24f62f5fdb0691b` | Applied as `c678740`: manual Tantivy reader reload, preserving existing writer mutex and explicit commit/reload calls | Tantivy 0.26.1 API inspected; repeated-commit/concurrent-read/delete regression added. Local test compilation exceeded 45 seconds; execution NOT RUN |
| `7280c0309fa848bb400362b71bf09d5cb3a7d314` | Applied as `87e8166`: rustls 0.23.45 → 0.23.46 | Cargo precise offline update; only version/checksum changed; locked offline metadata PASS |
| `4fec6cb5108895288405e1ffdabae63b76579f3a` | Deferred: optional Vite ^6.4.5 | Upstream lock patch also upgrades Rollup platform packages; local pnpm unavailable. Existing installed frontend validated without dependency installation |
| `6466a5e` | Deferred: source/external-ID search filters | Cross-layer authorization, retrieval and API contract changes require dedicated acceptance |
| `f0b31b1` | Deferred: search pagination/ranking metadata | Broad retrieval and response shape changes overlap native reranking/metadata work |
| `f879b45` | Deferred: temporal statement rewrite | Preserves open layer/phrase/attestation during revisions; requires store/temporal DB qualification |
| `fbe13bd` | Deferred: identity evidence preservation | Resolution/name-vector changes and migration; never import upstream numbering directly |
| `beb65fc` | Deferred: typed conflict governance | Store/API/review UI/migration changes need domain-specific reconciliation |
| `04376a2` | Deferred: backup/restore protection | Large CLI/restore test surface; evaluate in separate backup/restore qualification |
| `3b09f9f` | Deferred: human review for identity merges | Execution-gate/adjudication policy changes; related to provisional identities but not a safe isolated UI backport |

The main ref changes since the saved upstream backup were dependency-only; no
narrow independent frontend bug fix was identified for this pass. Product branding
is local Soorin work. Preserve `utopia-main-backup`: its independent history has
unique commits and no shared merge base with the Soorin feature history. Do not
force-delete it merely because an upstream ref contains the same commits.
