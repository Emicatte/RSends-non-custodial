# rsends-noncustodial — developer/CI targets.
.PHONY: e2e-anvil frontend-build check-python setup dev dev-infra dev-web

# ── Local dev bootstrap config ────────────────────────────────
# Interpreter used to CREATE the venv. Must be 3.12.x (pinned in
# services/backend/.python-version). Override: `make setup PYTHON=/path/to/python3.12`.
PYTHON  ?= python3.12
VENV    := services/backend/.venv
VENV_BIN := $(CURDIR)/services/backend/.venv/bin
COMPOSE := docker compose -f services/backend/docker-compose.dev.yml

# ── Python version gate ───────────────────────────────────────
# Fails loudly if the interpreter is missing or not 3.12.x, so the venv can
# never be (re)created on the wrong version again.
check-python:
	@command -v $(PYTHON) >/dev/null 2>&1 || { \
		echo "ERROR: '$(PYTHON)' not found on PATH."; \
		echo "  Install Python 3.12 — e.g.  brew install python@3.12  (or  pyenv install 3.12)"; \
		echo "  then retry, or run:  make setup PYTHON=/full/path/to/python3.12"; \
		exit 1; }
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' || { \
		echo "ERROR: '$(PYTHON)' is $$($(PYTHON) -V 2>&1), but Python 3.12.x is required"; \
		echo "  (pinned in services/backend/.python-version)."; \
		echo "  Install 3.12 or run:  make setup PYTHON=/full/path/to/python3.12"; \
		exit 1; }
	@echo "✓ Python OK: $$($(PYTHON) -V 2>&1)"

# ── One-command setup ─────────────────────────────────────────
# 3.12 venv + backend deps (+ editable install) + frontend npm + dev .env +
# Postgres/Redis up + migrations.
setup: check-python
	@test -d $(VENV) || { echo "→ creating venv ($(VENV))"; $(PYTHON) -m venv $(VENV); }
	$(VENV_BIN)/python -m pip install -U pip
	$(VENV_BIN)/python -m pip install -r services/backend/requirements.txt
	$(VENV_BIN)/python -m pip install -e services/backend
	$(VENV_BIN)/python scripts/gen_dev_env.py
	cd apps/web && npm install
	@$(MAKE) dev-infra
	@echo "→ running migrations (alembic upgrade head)"
	cd services/backend && ENVIRONMENT=development $(VENV_BIN)/alembic upgrade head
	@echo ""
	@echo "✓ Setup complete. Run:  make dev   (backend + frontend)"
	@echo "                  or:   make dev-web (frontend only)"

# ── Infra only ────────────────────────────────────────────────
# If Postgres+Redis are already listening (your own docker stack or brew
# services), reuse them. Otherwise bring them up via docker compose. Falls
# through with guidance if neither is possible.
dev-infra:
	@pg=$$(lsof -nP -iTCP:5432 -sTCP:LISTEN 2>/dev/null); rd=$$(lsof -nP -iTCP:6379 -sTCP:LISTEN 2>/dev/null); \
	if [ -n "$$pg" ] && [ -n "$$rd" ]; then \
		echo "→ Postgres+Redis already listening on :5432/:6379 — reusing them (skipping docker compose)"; \
	elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \
		echo "→ starting Postgres + Redis (docker compose)"; \
		$(COMPOSE) up -d --wait db redis; \
	else \
		echo "ERROR: Postgres/Redis not running and docker is unavailable."; \
		echo "  Start them with:  brew services start postgresql@16 redis   (see README)"; \
		exit 1; \
	fi

# ── Backend + frontend together (Ctrl-C stops both) ───────────
dev: dev-infra
	@echo "→ backend  http://localhost:8000   frontend  http://localhost:3000   (Ctrl-C to stop)"
	@trap 'kill 0' EXIT INT TERM; \
	( cd services/backend && ENVIRONMENT=development $(VENV_BIN)/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 ) & \
	( cd apps/web && npm run dev ) & \
	wait

# ── Frontend only (quick UI viewing, no backend/infra) ────────
dev-web:
	@if [ -x "$(VENV_BIN)/python" ] && [ ! -f apps/web/.env.local ]; then \
		$(VENV_BIN)/python scripts/gen_dev_env.py; \
	fi
	cd apps/web && npm run dev

# ── Existing targets ──────────────────────────────────────────
# One command to run the whole deterministic Anvil money-path E2E.
# Boots Anvil, deploys via Foundry, drives the indexer + webhook loop, and
# asserts both branches (USDC permit / USDT approve+pay) + the negative case.
# Requires `anvil` and `forge` on PATH (Foundry); installs the Python E2E deps.
e2e-anvil:
	cd services/backend && python -m pip install -q -r requirements-e2e.txt && \
	DATABASE_URL="sqlite+aiosqlite://" ENVIRONMENT=test \
	python -m pytest -m e2e tests/e2e -v

# Frontend gate: install + typecheck + production build.
frontend-build:
	npm install
	cd apps/web && npx tsc --noEmit && npx next build
