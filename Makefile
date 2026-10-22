.PHONY: setup db-up db-down db-check api ai web check

setup:
	python3 scripts/init_env.py
	uv sync --project services/ai --locked
	dotnet restore apps/api --locked-mode
	npm ci --prefix apps/web

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

db-check:
	docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < docs/database-check.sql

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
