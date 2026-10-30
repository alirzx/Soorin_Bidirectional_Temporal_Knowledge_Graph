# Upstream synchronization with clean Soorin history

The Soorin `main` branch starts with an independent root commit based on Utopia `v0.1.0-rc9`; importing Utopia's old Git commits into Soorin is intentional **not** part of this workflow.

Remotes:

- `personal`: `git@github.com:alirzx/Soorin_Bidirectional_Temporal_Knowledge_Graph.git`
- `upstream`: `https://github.com/deeplethe/utopia.git`
- `origin`: reserved for future organization remote.

A normal `git merge upstream/main` would attempt to join unrelated histories and should be avoided. Instead:

1. Record the last upstream revision integrated (initially tag `v0.1.0-rc9`).
2. `git fetch upstream --tags`.
3. Create a Soorin feature branch from `main`.
4. Review `git diff v0.1.0-rc9 upstream/main -- crates/ migrations/ web/ ...` for the **first** sync, or diff from the new recorded upstream baseline on subsequent syncs.
5. Apply only reviewed patches in the feature branch. Resolve conflicts, migrate schemas intentionally, run Rust/UI regression and SOC mock tests.
6. Commit **as Soorin commits** and merge a reviewed PR. Update the recorded upstream baseline tag/SHA.

`git diff ... | git apply --3way` is a possible starting point for carefully scoped paths, but **not** a blanket command when local modifications exist. In particular, exclude/inspect `README.md`, `.gitignore`, local Compose overrides, `docs/soorin/`, and `soorin/`.

License attribution remains required regardless of clean Git commit ancestry.
