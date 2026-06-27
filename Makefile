# StockLens Makefile
# ──────────────────────────────────────────────────────────────────────────────
# Development commands for the FastAPI backend.
# All Docker Compose operations assume docker-compose.yml at repo root.

.PHONY: up down rebuild test logs migrate alembic-autogenerate

up: ## Start all services (backend, postgres, redis, test DB)
	docker compose --profile test up -d

down: ## Stop all services
	docker compose down

rebuild: ## Rebuild the backend image and restart
	docker compose build backend && docker compose up -d

test: ## Run pytest suite in Docker (profile: test)
	docker compose run --rm pytest

logs: ## Tail logs from all services
	docker compose logs -f

migrate: ## Run Alembic migrations in the backend container
	docker compose exec backend alembic upgrade head

alembic-autogenerate: ## Generate a new Alembic migration revision
	@read -p "Enter migration message: " msg; \
	docker compose exec backend alembic revision --autogenerate -m "$$msg"
