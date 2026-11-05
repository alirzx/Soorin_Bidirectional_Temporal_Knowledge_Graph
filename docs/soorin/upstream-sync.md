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
