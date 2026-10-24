.PHONY: setup db-up db-down db-migrate db-check api-integration api ai web check

setup:
	python3 scripts/init_env.py
	uv sync --project services/ai --locked
	dotnet restore apps/api --locked-mode
	dotnet restore apps/api/tests/auth --locked-mode
	dotnet tool restore
	npm ci --prefix apps/web

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

db-migrate:
	set -a; . ./.env; set +a; python3 scripts/db/migrate.py
	set -a; . ./.env; set +a; python3 scripts/db/provision_search.py

db-check:
	dotnet build apps/api --no-restore
	python3 apps/api/tests/integration.py
	python3 -m unittest discover -s tests -p 'test_search_schema.py' -v

api-integration: db-check


api:
	set -a; . ./.env; set +a; dotnet run --project apps/api

ai:
	set -a; . ./.env; set +a; uv run --project services/ai --locked uvicorn findie_ai.main:app --app-dir services/ai --host 127.0.0.1 --port 8000

web:
	npm run dev --prefix apps/web

check:
	python3 -m unittest discover -s tests -v
	uv run --project services/ai --locked pytest services/ai/tests
	dotnet build apps/api --no-restore
	python3 apps/api/tests/smoke.py
	npm test --prefix apps/web
	npm run build --prefix apps/web
