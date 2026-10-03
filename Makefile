.PHONY: install db migrate dev-api test-api lint-api typecheck build

install:
	npm install
	python3 -m venv .venv
	.venv/bin/pip install -e 'services/api[dev]'

db:
	docker compose up -d postgres redis

migrate:
	cd services/api && ../../.venv/bin/alembic upgrade head

dev-api:
	.venv/bin/uvicorn concierge.main:app --app-dir services/api/src --reload --port 8000

# Tests need a real PostgreSQL (row-level security is part of what is tested).
test-api:
	TEST_OWNER_URL=postgresql+psycopg://concierge:concierge@localhost:5432/concierge_test \
	TEST_APP_URL=postgresql+psycopg://concierge_app:app@localhost:5432/concierge_test \
	.venv/bin/pytest services/api/tests

lint-api:
	.venv/bin/ruff check services/api
	.venv/bin/ruff format --check services/api

typecheck:
	npm run typecheck
	.venv/bin/mypy services/api/src

build:
	npm run build
