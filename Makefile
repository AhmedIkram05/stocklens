# StockLens Makefile
# ──────────────────────────────────────────────────────────────────────────────
# Development commands for the FastAPI backend.
# All Docker Compose operations assume docker-compose.yml at repo root.

.PHONY: up down rebuild test logs migrate alembic-autogenerate backend-ml train train-all seed hpo hpo-phase2 rust-test

# Interpreter used for the Rust crate's tests. It must have numpy importable —
# the numpy crate loads numpy's C API capsule at runtime, so `cargo test`
# fails with "Failed to access NumPy array API capsule" otherwise.
FE_PYTHON ?= python3
REPO_ROOT := $(CURDIR)
BACKEND_DIR := $(REPO_ROOT)/backend
ML_PYTHON ?= /tmp/ml_venv/bin/python
DATABASE_URL ?= postgresql+asyncpg://stocklens:stocklens@localhost:5432/stocklens

rust-test: ## Run the features-engine Rust test suite (needs numpy in $(FE_PYTHON))
	@$(FE_PYTHON) -c 'import numpy' 2>/dev/null || \
		{ echo "$(FE_PYTHON) has no numpy — pip install numpy into it, or run: make rust-test FE_PYTHON=/path/to/python"; exit 1; }
	cd backend/ml/features-engine && \
	PYO3_PYTHON="$$($(FE_PYTHON) -c 'import sys; print(sys.executable)')" \
	PYTHONPATH="$$($(FE_PYTHON) -c 'import site; print(site.getsitepackages()[0])')" \
	cargo test --locked

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
	PYTHONPATH="$(BACKEND_DIR)" \
	DATABASE_URL=$(DATABASE_URL) \
	TRAINING_TICKERS="$(TRAINING_TICKERS)" \
	MLFLOW_TRACKING_URI=http://localhost:5001 \
	MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=true \
	MODEL_ARTIFACT_DIR=/tmp/model_artifacts/champion \
	$(ML_PYTHON) -m ml.pipeline
	@echo "=== Deploying model to Docker volume ==="
	docker compose cp /tmp/model_artifacts/champion/model.pt backend:/model_artifacts/champion/model.pt
	docker compose exec -u root backend chown appuser:appuser /model_artifacts/champion/model.pt
	docker compose restart backend
	@echo "=== Model trained and deployed ==="

hpo: backend-ml ## Run Optuna HPO Phase 1 on macOS MPS GPU (host /tmp/ml_venv)
	PYTHONPATH="$(BACKEND_DIR)" \
	DATABASE_URL=$(DATABASE_URL) \
	MLFLOW_TRACKING_URI=http://localhost:5001 \
	MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=true \
	$(ML_PYTHON) -m ml.hpo

hpo-phase2: backend-ml ## Sweep threshold_mult using Phase 1 best HPs on macOS MPS GPU
	PYTHONPATH="$(BACKEND_DIR)" \
	DATABASE_URL=$(DATABASE_URL) \
	MLFLOW_TRACKING_URI=http://localhost:5001 \
	MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=true \
	$(ML_PYTHON) -m ml.hpo --phase 2

train-all: backend-ml ## Train on full S&P 500 (~7min/epoch, hours total)
	$(MAKE) train TRAINING_TICKERS=ALL

seed: backend-ml ## Seed OHLCV data from host (raw Yahoo v8 chart API; backend/scripts/seed_ohlcv.py)
	PYTHONPATH="$(BACKEND_DIR)" \
	"$(BACKEND_DIR)/.venv/bin/python" "$(BACKEND_DIR)/scripts/seed_ohlcv.py"
