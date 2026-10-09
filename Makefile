.PHONY: install test lint eval seed run up down
install:
	cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]" && cd ../frontend && npm ci
test:
	cd backend && .venv/bin/python -m pytest -q
test-pg:
	cd backend && .venv/bin/python scripts/pg_test.py
lint:
	cd backend && .venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit
eval:
	cd backend && .venv/bin/python -m evals.run
seed:
	cd backend && .venv/bin/python -m app.seed --reset
run:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
up:
	docker compose up --build -d
down:
	docker compose down -v
