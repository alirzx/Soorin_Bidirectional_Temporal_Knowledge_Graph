# Local development

Repository: `/mnt/X/Soorin/soorin_bi_TKG/utopia`; development branch:
`feature/soc-knowledge-foundation-v1`. Preserve existing services and volumes.
Both the historical 1516/1517 lab and the 2516/2517 source-build project may already
exist; inventory ports, container/project names and mounted volumes before startup.
A new project name alone does not prevent a published-port collision.

`docker-compose.soorin-dev.yml` builds this source and uses separate named database
and data volumes. `docker-compose.models.yml` adds optional embedding/reranker/NER
profiles, loopback ports 2811/2812/2813 and read-only cache mounts. Model download
needs an explicitly writable cache mount and never loads weights.

Start with [Pre-build validation](PREBUILD_VALIDATION.md). Perform expensive setup
only in the approved phase described in [Build handoff](BUILD_AND_TEST_HANDOFF.md).
Do not build/start a stack during a lightweight-only task. Use synthetic accounts,
KBs and Statements sources; never convert an existing folder source to Statements.

Production uses [Production deployment](PRODUCTION_DEPLOYMENT.md) and its explicit
Soorin image variable, not generic upstream-image Compose. Keep secrets outside Git.
The default CORS origin is the local frontend dev server; production overrides it
with the exact TLS origin. Runtime and model settings are separate: workspace
settings activate native clients; Python evaluation env vars do not.


## Next V1 disposable QA project (prepared, NOT RUN)

Use `soorin/config/qa.env.example` with existing `docker-compose.soorin-dev.yml`.
It sets COMPOSE_PROJECT_NAME=soorin-tkg-v1-qa, app 127.0.0.1:2526 and DB
127.0.0.1:2527. Verify port ownership again during the future build mission.
Volumes resolve to `soorin-tkg-v1-qa_soorin_sprint1_db` and
`soorin-tkg-v1-qa_soorin_sprint1_data`; no external volume/bind reuse is configured.
Replace the example DB password with an operator-owned secret before startup.
Always pass `--env-file` and `-p soorin-tkg-v1-qa` explicitly. Static check only:

```bash
docker compose --env-file soorin/config/qa.env.example -p soorin-tkg-v1-qa \
  -f docker-compose.soorin-dev.yml config --quiet
```

No build/up/down is authorized by this documentation. Existing labs at 1516/2516
must remain intact. Both E2E harnesses require explicit QA project/approved port
and verify app/db labels, exact project-owned mounts and loopback mappings before
any HTTP mutation. Offline preflight remains available without Docker access.
Use [manual preview](MANUAL_SOC_INGESTION.md) first; native_validation is the
canonical receipt harness, local_validation remains a legacy Statements harness.
Do not combine their sources. Optional model profiles remain absent by default;
the development overlay's 2811–2813 bindings also need inventory before use.

## Makefile entry points for the disposable V1 QA build

The old `make e2e-live` command targets the pre-existing 2516 lab and is
intentionally disabled. The V1 QA commands below select an independent Compose
project and the isolated 2526/2527 ports. Run these only in the separately approved
local-build window, **after** verifying those ports are free and the target volumes
are new and disposable:

```bash
make qa-env-init        # writes .env.qa once with a random DB password, mode 0600
make qa-config          # static Compose validation; no startup
make qa-build           # builds the application image; next phase only
make qa-up QA_EXECUTE=YES  # starts only QA db/app; next phase only
make qa-native-e2e E2E_EXECUTE=YES  # runs synthetic native acceptance after ownership check
```

The generated `.env.qa` is Git-ignored. Keep `QA_ENV_FILE`, `QA_PROJECT`,
`QA_APP_PORT` and `QA_DB_PORT` aligned with the actual Compose publication.
The native acceptance tool verifies Docker project labels, ports and volume names
before making HTTP mutations; a Makefile target does not certify a container's
identity by itself. The older generic Makefile `build`, `up`, `health`, and
`migrations` targets still use the legacy Sprint-1 defaults. Do not use those
for V1 QA. Do not run destructive cleanup against any pre-existing stack.
