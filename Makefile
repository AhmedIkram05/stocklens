# StockLens Makefile
# ──────────────────────────────────────────────────────────────────────────────
# Development commands for the FastAPI backend.
# All Docker Compose operations assume docker-compose.yml at repo root.

.PHONY: up down rebuild test logs migrate alembic-autogenerate backend-ml train train-all seed hpo hpo-phase2

up: ## Build & start all services (backend, ml, postgres, redis, mlflow, test DB, airflow)
	docker compose up -d
	cd airflow && docker compose up -d

down: ## Stop all services
	cd airflow && docker compose down
	docker compose down

rebuild: ## Rebuild the backend image and restart
	docker compose build backend
	docker compose up -d
	cd airflow && docker compose up -d

test: ## Run pytest suite in Docker (profile: test)
	docker compose run --rm pytest

logs: ## Tail logs from all services
	docker compose logs -f

migrate: ## Run Alembic migrations in the backend container
	docker compose exec backend alembic upgrade head

alembic-autogenerate: ## Generate a new Alembic migration revision
	@read -p "Enter migration message: " msg; \
	docker compose exec backend alembic revision --autogenerate -m "$$msg"

backend-ml: ## Ensure postgres + mlflow are running (required for train/seed)
	@echo "Starting postgres and mlflow services..."
	docker compose up -d postgres mlflow

train: backend-ml ## Train LSTM model on macOS MPS GPU (host venv, ~19s/epoch, 55 tickers)
	PYTHONPATH=/Users/ahmedikram/GitHub\ Repos/stocklens/backend \
	DATABASE_URL=postgresql+asyncpg://stocklens:stocklens@localhost:5432/stocklens \
	MLFLOW_TRACKING_URI=http://localhost:5001 \
	MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=true \
	MODEL_ARTIFACT_DIR=/tmp/model_artifacts/champion \
	/tmp/ml_venv/bin/python -m ml.pipeline
	@echo "=== Deploying model to Docker volume ==="
	docker compose cp /tmp/model_artifacts/champion/model.pt backend:/model_artifacts/champion/model.pt
	docker compose exec -u root backend chown appuser:appuser /model_artifacts/champion/model.pt
	docker compose restart backend
	@echo "=== Model trained and deployed ==="

hpo: backend-ml ## Run Optuna HPO Phase 1 on macOS MPS GPU (host /tmp/ml_venv)
	PYTHONPATH=/Users/ahmedikram/GitHub\ Repos/stocklens/backend \
	DATABASE_URL=postgresql+asyncpg://stocklens:stocklens@localhost:5432/stocklens \
	MLFLOW_TRACKING_URI=http://localhost:5001 \
	MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=true \
	/tmp/ml_venv/bin/python -m ml.hpo

hpo-phase2: backend-ml ## Sweep threshold_mult using Phase 1 best HPs on macOS MPS GPU
	PYTHONPATH=/Users/ahmedikram/GitHub\ Repos/stocklens/backend \
	DATABASE_URL=postgresql+asyncpg://stocklens:stocklens@localhost:5432/stocklens \
	MLFLOW_TRACKING_URI=http://localhost:5001 \
	MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=true \
	/tmp/ml_venv/bin/python -m ml.hpo --phase 2

train-all: backend-ml ## Train on full S&P 500 (~7min/epoch, hours total)
	$(MAKE) train TRAINING_TICKERS="$$(python3 -c "from ml.config import _ALL_SP500; print(','.join(_ALL_SP500))")"

seed: backend-ml ## Seed OHLCV data from host (raw Yahoo v8 chart API)
	PYTHONPATH=/Users/ahmedikram/GitHub\ Repos/stocklens/backend \
	/Users/ahmedikram/GitHub\ Repos/stocklens/backend/.venv/bin/python scripts/seed_ohlcv.py
