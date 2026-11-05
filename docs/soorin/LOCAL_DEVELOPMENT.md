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
