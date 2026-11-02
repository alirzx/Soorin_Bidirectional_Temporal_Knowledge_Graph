SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV_FILE ?= .env
PROJECT ?= soorin-sprint1
DC = docker compose --env-file $(ENV_FILE) -p $(PROJECT) -f docker-compose.soorin-dev.yml
PYTHON ?= python3
OLD_IMAGE := ghcr.io/deeplethe/utopia:0.1.0-rc9
.PHONY: help env-init preflight config old-inspect old-remove image-remove build build-fresh up down ps health logs migrations offline mock-check e2e-offline e2e-live ner-install ner-smoke rust-check web-check
help:
	@echo 'Targets: env-init preflight old-inspect old-remove image-remove build build-fresh up down ps health logs migrations offline mock-check e2e-offline e2e-live ner-install ner-smoke rust-check web-check'
env-init:
	@test ! -e '$(ENV_FILE)' || { echo 'Environment file exists, refusing overwrite'; exit 1; }
	@command -v openssl >/dev/null
	@umask 077; { printf 'SOORIN_DEV_DB_PASSWORD=%s\n' "$$(openssl rand -hex 24)"; printf 'SOORIN_DEV_APP_BIND=127.0.0.1:2516\nSOORIN_DEV_DB_BIND=127.0.0.1:2517\nUTOPIA_DB_IMAGE=pgvector/pgvector:pg16\nSOORIN_BUILD_JOBS=1\nSOORIN_DEV_DB_MAX_CONNECTIONS=8\n'; } > '$(ENV_FILE)'
	@chmod 600 '$(ENV_FILE)'
	@echo 'Created $(ENV_FILE); preserve the password for existing volumes.'
config:
	@$(DC) config --quiet
preflight: config
	@docker info >/dev/null
	@docker compose version
	@$(DC) ps
	@echo 'Port collisions:'; ss -lnt 2>/dev/null | grep -E ':2516|:2517' || true
	@free -h; df -h .
old-inspect:
	@docker ps -a --filter name=utopia-app-1 --filter name=utopia-db-1 --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
	@docker image ls '$(OLD_IMAGE)'
	@docker volume ls --filter name=utopia
old-remove:
	@set -e; for cname in utopia-app-1 utopia-db-1; do \
	  id=$$(docker ps -aq --filter "name=^/$$cname$$"); \
	  if [ -z "$$id" ]; then echo "$$cname: absent"; continue; fi; \
	  state=$$(docker inspect -f '{{.State.Running}}' "$$id"); \
	  if [ "$$state" = true ]; then echo "REFUSING to remove running $$cname"; exit 1; fi; \
	  docker rm "$$id"; \
	done
	@echo 'Legacy named volumes preserved.'
image-remove:
	@set -e; if ! docker image inspect '$(OLD_IMAGE)' >/dev/null 2>&1; then echo 'Image absent'; exit 0; fi; \
	  if [ -n "$$(docker ps -aq --filter 'ancestor=$(OLD_IMAGE)')" ]; then echo 'Referenced by a container; inspect first'; exit 1; fi; \
	  docker image rm '$(OLD_IMAGE)'
build: config
	@$(DC) build app
build-fresh: config
	@$(DC) build --no-cache app
up: config
	@$(DC) up -d --no-build db app
down:
	@$(DC) down
ps:
	@$(DC) ps
health:
	@$(DC) ps
	@curl -fsS http://127.0.0.1:2516/api/v1/health
	@echo
	@curl -fsS -o /dev/null -w 'Frontend HTTP %{http_code}\n' http://127.0.0.1:2516/
logs:
	@$(DC) logs --tail=200 db app
migrations:
	@$(DC) exec -T db psql -U utopia -d utopia -c 'SELECT version, description, success FROM _sqlx_migrations WHERE version IN (111,112) ORDER BY version;'
offline:
	@$(PYTHON) -m compileall -q soorin
	@$(PYTHON) -m unittest discover -s soorin/tests -p 'test_*.py' -v
	@$(PYTHON) -m unittest discover -s soorin/tests/mock_splunk/tests -v
	@$(PYTHON) -m soorin.evaluation.graph_integrity soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json
	@$(PYTHON) -m soorin.evaluation.temporal_cases
	@$(PYTHON) -m soorin.evaluation.retrieval_benchmark
mock-check:
	@$(PYTHON) soorin/tests/mock_splunk/scripts/soc_mock.py validate
	@$(PYTHON) soorin/tests/mock_splunk/scripts/soc_mock.py render --output-dir /tmp/soorin-sprint1-mock-statements
e2e-offline:
	@$(PYTHON) -m soorin.e2e.local_validation --report /tmp/soorin-sprint1-e2e-offline.json
e2e-live:
	@test '$(E2E_EXECUTE)' = YES || { echo 'Set E2E_EXECUTE=YES only after isolated KB/source creation'; exit 1; }
	@test -n "$$UTOPIA_KB_ID" && test -n "$$UTOPIA_SOURCE_ID" && test -n "$$UTOPIA_INGEST_TOKEN" && test -n "$$UTOPIA_SESSION_TOKEN" || { echo 'Missing KB/source IDs or credentials'; exit 1; }
	@UTOPIA_BASE_URL=http://127.0.0.1:2516 $(PYTHON) -m soorin.e2e.local_validation --execute --report /tmp/soorin-sprint1-e2e-live.json
ner-install:
	@$(PYTHON) -m pip install -r soorin/requirements-ner-cpu.txt
ner-smoke:
	@$(PYTHON) -c "from soorin.extraction.cpu_cyber_ner import CpuCyberNer; print(CpuCyberNer(local_files_only=True).extract('Synthetic malware detected on a test host'))"
rust-check:
	@cargo fmt --all -- --check
	@cargo clippy --workspace --all-targets -- -D warnings
web-check:
	@cd web && pnpm test && pnpm typecheck && pnpm build
