# Soorin TKG: private LAN/VPN host binding for the source-build stack

This note applies to `docker-compose.soorin-dev.yml` (the existing source-build
QA/staging stack), **not** the hardened production Compose profile.

## Why no image rebuild is needed

The Rust server listens at `0.0.0.0:1516` **inside** its container. Docker
publishes that container port using the host-side `SOORIN_DEV_APP_BIND` value.
The default is loopback-only. Switching the host binding changes only Docker
container configuration: recreate **only** `app`, never the DB/model services.
The same container serves the React UI at `/` and API routes at `/api/v1/*`.

Use the actual private interface IP (for Server 55, `192.168.0.55`) and a
free host port (`2516` here). Do **not** change `SOORIN_DEV_DB_BIND`; keep
PostgreSQL and the three model ports bound to loopback. Do not publish the
database or model HTTP endpoints to the LAN.

## Server 55 controlled change

Preconditions: You are `api`, the existing stack is named
`soorin-tkg-server55`, and the current database, app data, and model cache
volumes must be preserved. Bootstrap the **first admin account privately**
before opening the interface. Confirm VPN/LAN firewall restrictions and that
untrusted networks cannot reach TCP/2516. This development profile serves
plain HTTP and is **not** a replacement for HTTPS/TLS proxying or the separate
runtime/migration DB roles required for production. Do not send credentials
over an untrusted network; use an SSH tunnel or approved HTTPS proxy where
transport confidentiality is required.

```bash
cd /home/api/Soorin_TKG
umask 077
cp -p .env ".env.pre-lan.$(date -u +%Y%m%dT%H%M%SZ).backup"
# Edit ONLY the existing line in ignored .env; leave the DB password untouched:
# SOORIN_DEV_APP_BIND=192.168.0.55:2516
grep '^SOORIN_DEV_APP_BIND=' .env
docker compose --env-file .env -p soorin-tkg-server55 \
  -f docker-compose.soorin-dev.yml config --quiet
# Check that TCP/2516 is free on the requested interface.
ss -lnt | grep ':2516' || true
# The app will be briefly unavailable; the DB and models stay running.
docker compose --env-file .env -p soorin-tkg-server55 \
  -f docker-compose.soorin-dev.yml \
  up -d --no-deps --no-build --pull never --force-recreate app
docker compose --env-file .env -p soorin-tkg-server55 \
  -f docker-compose.soorin-dev.yml ps
curl --fail-with-body -sS http://192.168.0.55:2516/api/v1/health
```

Then verify from an approved LAN/VPN client that the UI and API both respond
at `http://192.168.0.55:2516`; do not confuse reachability with authorization.
The UI and API are same-origin when served from this URL. If deploying the
frontend on another origin, configure the exact permitted CORS origin rather
than using a wildcard.

**Compose naming:** Explicit `-p soorin-tkg-server55` overrides
`COMPOSE_PROJECT_NAME` from `.env`. Do not change the project name to
`soorin-tkg` while these volumes are in use: that would select a new set of
Compose-scoped containers and volumes. Do not run `down -v`, `prune`, or
`up --build` to change the published host IP.

To reverse the publication, restore `SOORIN_DEV_APP_BIND=127.0.0.1:2516`
in the **same** `.env` and re-run the **app-only** `up` command above.
