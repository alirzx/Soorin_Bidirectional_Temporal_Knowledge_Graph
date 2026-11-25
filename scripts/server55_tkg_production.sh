#!/usr/bin/env bash
# Immutable-image deployment interface. Application builds and live rollout are separate.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${SOORIN_PROD_ENV_FILE:-$ROOT/.env}"
TKG_NETWORK="${SOORIN_SOC_INTEGRATION:-off}"
PROJECT=soorin-tkg-server55
C=(docker compose --project-directory "$ROOT" --env-file "$ENV_FILE" -p "$PROJECT"
   -f docker-compose.production.yml -f docker-compose.models-production.yml --profile models)
case "$TKG_NETWORK" in
  off) ;;
  on) C+=(-f docker-compose.tkg-network.override.yml) ;;
  *) echo 'FAIL: SOORIN_SOC_INTEGRATION must be off or on' >&2; exit 2 ;;
esac
if [[ -n "${SOORIN_PROD_RUNTIME_OVERRIDE:-}" ]]; then
  C+=(-f "$SOORIN_PROD_RUNTIME_OVERRIDE")
fi

resolved() {
  [[ -s "$ENV_FILE" ]] || { echo 'FAIL: production environment file missing' >&2; return 1; }
  "${C[@]}" config --format json 2>/dev/null || { echo 'FAIL: production Compose inputs could not resolve' >&2; return 1; }
}

case "${1:-}" in
  config) resolved | python3 scripts/qualify_production_compose.py "$TKG_NETWORK" ;;
  preflight) resolved | python3 scripts/qualify_production_compose.py "$TKG_NETWORK" --runtime ;;
  status) "${C[@]}" ps -a ;;
  images) "${C[@]}" images ;;
  *) echo 'Usage: bash scripts/server55_tkg_production.sh config|preflight|status|images' >&2; exit 2 ;;
esac
