.PHONY: install db migrate seed-demo demo-site dev-api test-api lint-api typecheck build

install:
	npm install
	python3 -m venv .venv
	.venv/bin/pip install -e 'services/api[dev]'

db:
	docker compose up -d postgres redis

migrate:
	cd services/api && ../../.venv/bin/alembic upgrade head

seed-demo:
	cd services/api && ../../.venv/bin/python -m concierge.cli seed-demo

# Serves a pretend customer website on http://localhost:8080 with the widget embedded.
demo-site:
	npm run build:embed --workspace @concierge/widget
	cp apps/widget/dist-embed/widget.js apps/widget/test-site/widget.js
	cd apps/widget/test-site && python3 -m http.server 8080

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
