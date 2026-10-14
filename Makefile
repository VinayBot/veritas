.PHONY: setup dev test lint format eval redteam models doctor demo up down backend-dev frontend-dev backend-test frontend-test backend-lint frontend-lint pii-eval planner-eval

# Some machines only have the standalone `docker-compose` binary, others only the `docker
# compose` plugin — detected at runtime rather than hardcoding one and breaking on the other.
DOCKER_COMPOSE := $(shell command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo docker compose)

setup:
	[ -f .env ] || cp .env.example .env
	cd backend && uv sync && uv run pre-commit install
	cd frontend && npm install

dev:
	@trap 'kill 0' EXIT INT TERM; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

test: backend-test frontend-test

backend-test:
	cd backend && uv run pytest

frontend-test:
	cd frontend && npm run test --if-present

lint: backend-lint frontend-lint

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app

frontend-lint:
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .

eval:
	cd backend && uv run python scripts/run_eval.py

redteam:
	cd backend && uv run python scripts/run_redteam.py

pii-eval:
	cd backend && uv run python scripts/eval_pii.py

planner-eval:
	cd backend && uv run python scripts/eval_planner.py

# Pre-downloads and verifies every model (Docling, spaCy/Presidio, embedder, reranker) plus
# Ollama + vector-store reachability — run this once after `make setup` so the cold-cache cost
# (~4 minutes on first run, see docs/TROUBLESHOOTING.md) happens here, not on a user's upload.
models:
	cd backend && uv run python scripts/warm_models.py

# Read-only — never downloads or modifies anything, unlike `make models`. Run this first when
# something isn't working: Ollama reachability + which required models are actually pulled,
# whether the optional cloud keys / required PII_VAULT_KEY are set, and whether the data
# directory is writable.
doctor:
	cd backend && uv run python scripts/doctor.py

# Deliberately narrow: real unfinished-work markers only. A broader word-match on "stub" or
# "placeholder" would flag HTML `placeholder=` attributes and honest prose explaining a
# *finished* design decision (e.g. "no stub here, see docs/DECISIONS.md") — false positives
# that teach everyone to ignore the gate. This instead matches only the concrete, actionable
# markers of code that doesn't actually do anything yet.
no-stubs:
	@! grep -rnE "TODO|FIXME|NotImplementedError|raise NotImplemented" \
		--include='*.py' --include='*.ts' --include='*.tsx' \
		backend/app frontend/src \
		|| (echo "Found unfinished-work markers in production code (see above)." && exit 1)

demo:
	cd backend && uv run python scripts/demo.py

up:
	$(DOCKER_COMPOSE) up --build

down:
	$(DOCKER_COMPOSE) down

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev
