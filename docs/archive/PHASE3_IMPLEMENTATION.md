# Phase 3 — LSTM Directional Forecasting Implementation Plan

> **Status:** Draft
> **Last updated:** 2026-07-02
> **Depends on:** Phase 2 (OHLCV data in PostgreSQL for 50+ S&P 500 tickers + portfolio tickers)
> **Target tests:** 80+ new tests across ML module features, labeling, dataset, model, evaluation, and prediction endpoint
> **Architecture decision:** Global multi-ticker model with entity embeddings (see ADR in grill session)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [New Modules](#new-modules)
4. [Implementation Rounds](#implementation-rounds)
   - [Round 1 — ML Infrastructure](#round-1--ml-infrastructure)
   - [Round 2 — Feature Engineering & Dataset](#round-2--feature-engineering--dataset)
   - [Round 3 — LSTM Model Definition](#round-3--lstm-model-definition)
   - [Round 4 — MLflow Integration & Training Pipeline](#round-4--mlflow-integration--training-pipeline)
   - [Round 5 — Production Predict Endpoint](#round-5--production-predict-endpoint)
   - [Round 6 — Full Training Execution](#round-6--full-training-execution)
   - [Round 7 — Frontend Integration](#round-7--frontend-integration)
5. [Testing Strategy](#testing-strategy)
6. [Success Criteria](#success-criteria)
7. [Risks & Mitigations](#risks--mitigations)
8. [Verification Checklist](#verification-checklist)

---

## Overview

Phase 3 adds a PyTorch LSTM directional forecasting model trained on 50+ S&P 500 components simultaneously (global multi-ticker approach with entity embeddings). The model predicts UP/FLAT/DOWN for any ticker using 30-day feature windows of technical indicators. A separate ML container handles training with MLflow tracking, and the existing FastAPI backend gains a prediction endpoint that loads the champion model at startup. The frontend receives LSTM-based projections replacing hardcoded CAGR assumptions.

### Key Deliverables

1. **ML infrastructure** — PyTorch training container, MLflow tracking server, shared model artifacts volume
2. **Feature engineering** — Log returns, moving averages, RSI, MACD, rolling volatility from adjusted_close
3. **Adaptive labeling** — UP/FLAT/DOWN labels using 0.5 x sigma_30d volatility threshold
4. **GlobalLSTM model** — Entity embeddings (16-dim) + 2-layer LSTM (hidden 128, dropout 0.3) + 3-class softmax
5. **Training pipeline** — Chronological 70/15/15 split, weighted cross-entropy, early stopping (patience 10)
6. **MLflow integration** — Hyperparams, loss curves, confusion matrix, evaluation metrics, model artifact
7. **Prediction endpoint** — GET /predict/{ticker} with Redis 6h cache, model loaded at startup
8. **Frontend integration** — LSTM predictions in SummaryScreen, ReceiptDetailsScreen, new PredictionCard component

### Dependencies

| Dependency   | Version  | Purpose                                     |
| ------------ | -------- | ------------------------------------------- |
| torch        | >=2.12.0 | LSTM model definition, training, inference  |
| mlflow       | >=3.14.0 | Experiment tracking, model registry         |
| scikit-learn | >=1.6.0  | Evaluation metrics (F1, confusion matrix)   |
| numpy        | >=2.1.0  | Array operations for feature engineering    |
| pandas       | >=2.3.0  | DataFrame manipulation for OHLCV processing |
| matplotlib   | >=3.10.0 | Loss curves and confusion matrix plots      |

---

## Architecture

### Module Structure

```
backend/
├── ml/                                    # NEW: ML training module (separate container)
│   ├── __init__.py
│   ├── pyproject.toml                     # ML-specific dependencies (uv-managed)
│   ├── Dockerfile                         # PyTorch + MLflow runtime
│   ├── config.py                          # ML configuration dataclass
│   ├── features.py                        # Technical indicator computation
│   ├── labeling.py                        # Adaptive UP/FLAT/DOWN labeling
│   ├── dataset.py                         # SequenceDataset with chronological split
│   ├── model.py                           # GlobalLSTM PyTorch module
│   ├── train.py                           # Training loop with early stopping
│   ├── evaluate.py                        # Directional accuracy, F1, simulated Sharpe
│   ├── utils.py                           # Device detection, seed setting, vocab builder
│   ├── mlflow_manager.py                  # MLflow run management, model registration
│   └── pipeline.py                        # Orchestrator: fetch to features to train to log
│
├── src/
│   ├── prediction/                        # NEW: Production prediction module (in backend)
│   │   ├── __init__.py
│   │   ├── schemas.py                     # PredictionResponse, PredictionRequest
│   │   ├── service.py                     # PredictionService - model loading, inference
│   │   └── router.py                      # GET /predict/{ticker} with Redis cache
│   │
│   ├── config.py                          # MODIFY: add ML/prediction settings
│   ├── main.py                            # MODIFY: register prediction router, model loading
│   ├── database/schema.py                 # model_registry table already exists
│   └── ... (existing modules unchanged)
│
├── Dockerfile                             # MODIFY: add torch (CPU inference only)
├── pyproject.toml                         # MODIFY: add torch to backend deps
│
└── tests/
    ├── test_ml/                           # NEW: ML unit tests (no DB needed)
    │   ├── __init__.py
    │   ├── test_features.py               # Feature computation tests
    │   ├── test_labeling.py               # Adaptive label tests
    │   ├── test_dataset.py                # Sequence dataset tests
    │   ├── test_model.py                  # Model forward pass tests
    │   └── test_evaluate.py               # Evaluation metric tests
    └── test_prediction.py                 # Prediction endpoint tests (uses conftest)

docker-compose.yml                         # MODIFY: add ml, mlflow services + volumes

frontend/src/
├── services/
│   ├── prediction.ts                      # NEW: frontend prediction service
│   ├── projectionService.ts               # MODIFY: add LSTM prediction fallback
│   └── market.ts                          # MODIFY: add prediction response types
│
├── screens/
│   ├── SummaryScreen.tsx                  # MODIFY: use LSTM projection instead of hardcoded 10%
│   └── ReceiptDetailsScreen.tsx           # MODIFY: add prediction badges
│
└── components/
    └── PredictionCard.tsx                 # NEW: prediction display component
```

### Data Flow - Training

```
docker compose run ml python -m ml.pipeline
  -> ml/pipeline.py
    -> asyncpg: fetch 5yr OHLCV for 55 tickers from ohlcv_prices
    -> ml/features.py: compute technical indicators per ticker
    -> ml/labeling.py: compute adaptive labels per ticker
    -> ml/utils.py: build ticker vocabulary (embedding indices)
    -> ml/dataset.py: merge all tickers -> SequenceDataset -> chronological split 70/15/15
    -> ml/model.py: initialise GlobalLSTM
    -> ml/train.py: train with Adam + weighted cross-entropy + early stopping
    -> ml/evaluate.py: directional accuracy, per-class F1, confusion matrix, simulated Sharpe
    -> ml/mlflow_manager.py: log run to MLflow
    -> ml/pipeline.py: register champion -> save to shared volume -> record in model_registry DB
```

### Data Flow - Prediction

```
Client -> GET /predict/{ticker}
  -> Try Redis GET predict:{ticker} (6h TTL cache)
  -> If cache HIT -> return cached PredictionResponse
  -> If cache MISS:
    -> prediction/service.py (lifespan-loaded GlobalLSTM):
      1. Fetch 90+ days OHLCV from market/repository.py (DB cache)
      2. Compute technical indicators (30-day window x N features)
      3. Convert to tensor -> model forward pass
      4. Apply softmax -> argmax for direction
      5. Return { ticker, direction, confidence, probabilities, model_version }
    -> Cache in Redis SETEX predict:{ticker} 21600 <json>
    -> Return PredictionResponse
```

---

## Implementation Rounds

### Round 1 - ML Infrastructure (Docker + MLflow)

**Goal:** PyTorch training container, MLflow tracking server, shared volumes for model artifacts. Backend gets torch for inference.

**Files to create:** 3 (ml/**init**.py, ml/Dockerfile, ml/pyproject.toml)
**Files to modify:** 3 (docker-compose.yml, backend/Dockerfile, backend/pyproject.toml)

---

#### Step 1.1 - Create ML directory skeleton

**File:** backend/ml/**init**.py
**Action:** Empty module marker.

```python
"""
StockLens ML module - PyTorch LSTM directional forecasting.

This module runs as a separate Docker Compose service (not part of the backend).
It trains a global multi-ticker LSTM model and logs results to MLflow.
"""

from __future__ import annotations
```

**Verify:** File is importable: `python -c "import ml"` (after Docker build).

---

#### Step 1.2 - Create ML pyproject.toml

**File:** backend/ml/pyproject.toml
**Action:** Define ML-specific dependencies managed by uv.

```toml
[project]
name = "stocklens-ml"
version = "0.1.0"
description = "StockLens ML training pipeline - PyTorch LSTM directional forecasting"
requires-python = ">=3.14"
dependencies = [
    "torch>=2.12.0",
    "mlflow>=3.14.0",
    "scikit-learn>=1.6.0",
    "numpy>=2.1.0",
    "pandas>=2.3.0",
    "matplotlib>=3.10.0",
    "asyncpg>=0.30.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
]
```

**Verify:** `uv sync` succeeds inside the ML build context.

---

#### Step 1.3 - Create ML Dockerfile

**File:** backend/ml/Dockerfile
**Action:** Multi-stage build with uv, installs PyTorch (CPU) and MLflow.

```dockerfile
# Stage 1: Build dependencies with uv
FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev


# Stage 2: Runtime image
FROM python:3.14-slim AS runtime

# Install curl for healthcheck, libgomp for torch parallelism
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy uv for dep management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY . .

# Non-root user
RUN groupadd -r mluser && useradd -r -g mluser -u 1001 mluser \
    && chown -R mluser:mluser /app

USER mluser

# No default CMD - runs via 'docker compose run ml python -m ml.pipeline'
```

**Why:** Same two-stage uv pattern as the backend Dockerfile. CPU-only PyTorch (no CUDA libs) keeps image size manageable (~1.2GB with torch). libgomp1 for OpenMP parallelism in torch.

**Note (ponytail):** GPU passthrough not configured for dev. Add --gpus all and CUDA base image when training on GPU instances in production.

**Verify:** `docker compose build ml` succeeds.

---

#### Step 1.4 - Add MLflow + ML services to docker-compose.yml

**File:** docker-compose.yml
**Action:** Add MLflow tracking server, ML training service, shared volumes.

```yaml
services:
  # ... existing services unchanged ...

  mlflow:
    image: python:3.14-slim
    ports:
      - '5000:5000'
    environment:
      MLFLOW_TRACKING_URI: http://0.0.0.0:5000
      MLFLOW_BACKEND_STORE_URI: sqlite:///mlflow/mlflow.db
      MLFLOW_ARTIFACT_ROOT: /mlflow/artifacts
    command: >
      sh -c "pip install mlflow>=3.14.0 --quiet &&
             mlflow server --host 0.0.0.0 --port 5000
             --backend-store-uri sqlite:///mlflow/mlflow.db
             --default-artifact-root /mlflow/artifacts"
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:5000']
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
    volumes:
      - mlflow_data:/mlflow
    restart: unless-stopped

  ml:
    build:
      context: ./backend/ml
    profiles:
      - ml
    environment:
      DATABASE_URL: postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens
      MLFLOW_TRACKING_URI: http://mlflow:5000
      MLFLOW_ARTIFACT_ROOT: /mlflow/artifacts
      MODEL_ARTIFACT_DIR: /model_artifacts/champion
      ENVIRONMENT: development
    depends_on:
      postgres:
        condition: service_healthy
      mlflow:
        condition: service_healthy
    volumes:
      - model_artifacts:/model_artifacts
      - mlflow_data:/mlflow
    # No ports - runs on-demand via: docker compose run ml python -m ml.pipeline

  # ... pytest service unchanged ...

volumes:
  pgdata:
  mlflow_data: # NEW: MLflow metadata + artifacts
  model_artifacts: # NEW: Champion model weights for backend inference
```

**Why:** MLflow runs as a standalone server with SQLite backend (no PostgreSQL dependency). Artifacts (model files, plots) stored on mlflow_data volume. The ML training service shares model_artifacts volume with the backend for model inference. ML service has profiles: [ml] so it's not started by default.

**Edge cases:**

- MLflow server restart: SQLite backend is persistent on volume, runs survive restart
- ML container failure: non-service (runs on-demand), no restart policy needed
- Race condition on model_artifacts volume: training writes atomically (write to temp, rename)

**Verify:** `docker compose config` shows 8 services (postgres, postgres_test, redis, backend, mlflow, ml, pytest, plus ml is under test profile). `docker compose up -d mlflow` starts tracking server.

---

#### Step 1.5 - Add PyTorch to backend Dockerfile for inference

**File:** backend/Dockerfile
**Action:** Add torch (CPU-only) to the builder stage. This keeps the inference runtime small (~200MB extra).

```dockerfile
# In the builder stage, after COPY pyproject.toml uv.lock .:
# No change needed here - uv sync handles pyproject.toml deps

# In the runtime stage, after system packages:
# No additional system packages needed for torch CPU inference
```

**Note:** The actual change is in pyproject.toml (Step 1.6). The Dockerfile stays the same - uv sync will pick up the new dependency.

#### Step 1.5a - Add ml/ directory to backend Dockerfile

**File:** backend/Dockerfile
**Action:** Copy the `ml/` directory into the backend image (prediction service imports from `ml.features`, `ml.model`, `ml.config`).

```dockerfile
# After COPY src/ src/:
COPY ml/ ml/
```

**Why:** Without this, `from ml.config import ML_CONFIG` fails with `ModuleNotFoundError` at runtime. The `ml/` directory contains feature engineering, model config, and model definition code reused by the prediction service.

**Risk:** Low. Standard `COPY` operation.

**Verify:** `docker compose build backend` succeeds and the `/app/ml/` directory exists in the container.

---

#### Step 1.5b - Add ml/ volume mount and prediction settings to docker-compose.yml

**File:** docker-compose.yml
**Action:** Add `./backend/ml:/app/ml` volume mount to the backend service for development hot-reload, and add the model artifacts read path.

```yaml
backend:
  # ... existing config ...
  volumes:
    - ./backend/src:/app/src
    - ./backend/ml:/app/ml # NEW: feature/model code for prediction service
    - model_artifacts:/model_artifacts # NEW: read champion model (moved from Step 5.6)
```

Also add the `pandas` and `numpy` dependencies to `backend/pyproject.toml`:

```toml
dependencies = [
    ...
    "torch>=2.12.0",
    "pandas>=2.3.0",
    "numpy>=2.1.0",
]
```

**Why:** The prediction service needs `ml/` at both build time (Dockerfile COPY) and runtime (volume mount for development iteration). pandas and numpy are required by `ml.features` but were only implicit transitive deps via yfinance before.

**Verify:** `docker compose config` shows the new volume mount. Backend container can `python -c "from ml.config import ML_CONFIG"` without errors.

---

**Why:** torch CPU-only for inference on the backend. No CUDA needed - the model is small (2MB weights, 128-hidden LSTM). Forward pass is ~10-50ms on CPU.

---

#### Step 1.6 - Add PyTorch to backend pyproject.toml

**File:** backend/pyproject.toml
**Action:** Add torch to the dependencies list.

```toml
dependencies = [
    ...
    "torch>=2.12.0",
]
```

**Verify:** `docker compose build backend` succeeds. Check image size is reasonable (~1.0GB with torch CPU, vs ~600MB without).

**Risk:** Medium. torch adds ~200MB to the production image. If image size is a concern, use `--find-links https://download.pytorch.org/whl/cpu` to install the CPU-only wheel which is smaller.

---

### Round 2 - Feature Engineering & Dataset

**Goal:** Pure functions for computing technical indicators, adaptive labels, and sequence datasets from OHLCV data. Zero DB access - fully testable with numpy/pandas.

**Files to create:** 5 (ml/features.py, ml/labeling.py, ml/dataset.py, ml/utils.py, ml/config.py)
**Files to modify:** 0

---

#### Step 2.1 - ML Configuration

**File:** backend/ml/config.py
**Action:** Dataclass for all ML training and inference configuration.

```python
"""
ML configuration - single source of truth for training and inference settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MLConfig:
    """All ML training and inference configuration."""

    # Sequence settings
    SEQUENCE_LENGTH: int = 30
    N_FEATURES: int = 13  # log_ret_1d, log_ret_5d, log_ret_21d, ma_5, ma_10, ma_20, ma_50, rsi_14, macd, macd_signal, macd_hist, vol_30d, vol_rank

    # Labeling
    VOL_LOOKBACK: int = 30
    THRESHOLD_MULT: float = 0.5

    # Model architecture
    EMBED_DIM: int = 16
    HIDDEN_DIM: int = 128
    N_LAYERS: int = 2
    DROPOUT: float = 0.3
    N_CLASSES: int = 3  # DOWN, FLAT, UP

    # Training
    EPOCHS: int = 100
    BATCH_SIZE: int = 64
    LEARNING_RATE: float = 1e-3
    WEIGHT_DECAY: float = 1e-5
    PATIENCE: int = 10  # early stopping patience
    MIN_DELTA: float = 1e-4  # minimum validation loss improvement

    # Split
    TRAIN_SPLIT: float = 0.7
    VAL_SPLIT: float = 0.15
    TEST_SPLIT: float = 0.15

    # Data
    TRAINING_TICKERS: list[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "UNH",
        "XOM", "JNJ", "WMT", "PG", "MA", "CVX", "HD", "MRK", "ABBV", "KO",
        "PEP", "AVGO", "COST", "CRM", "BAC", "TMO", "MCD", "ABT", "ACN", "DIS",
        "DHR", "LIN", "NFLX", "CSCO", "ADBE", "NEE", "CMCSA", "PFE", "TXN", "BMY",
        "AMGN", "PM", "QCOM", "RTX", "IBM", "HON", "CAT", "INTU", "AMAT", "AMT",
        "MS", "PLD", "SBUX", "VZ", "GE",
    ])
    OHLCV_YEARS: int = 5  # How many years of history to fetch

    # Paths
    MODEL_ARTIFACT_DIR: str = field(
        default_factory=lambda: os.environ.get("MODEL_ARTIFACT_DIR", "/model_artifacts/champion")
    )
    MLFLOW_TRACKING_URI: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    )
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens")
    )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Return a sync psycopg2-compatible DSN for pandas.read_sql.

        Strips the ``+asyncpg`` suffix from the async DSN.
        Stored as a property so it stays DRY and survives DSN format changes.
        """
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

    # Inference
    MIN_OHLCV_DAYS: int = 60  # Minimum days needed for feature computation (30 window + padding)
    PREDICTION_CACHE_TTL: int = 21600  # 6 hours in seconds

    # Class names
    CLASS_NAMES: tuple[str, ...] = ("DOWN", "FLAT", "UP")


ML_CONFIG = MLConfig()
```

**Why:** Frozen dataclass prevents accidental mutation. Single import for all ML settings. Environment variable overrides for containerised deployment. Training tickers include 55 well-known S&P 500 components plus room for portfolio tickers.

---

#### Step 2.2 - Feature Engineering

**File:** backend/ml/features.py
**Action:** Compute all 13 technical indicators from OHLCV data.

```python
"""
Technical indicator computation from OHLCV data.

All functions are pure (no DB, no IO) and operate on numpy arrays or
pandas DataFrames. Every function handles NaN/inf edge cases.

Returns a DataFrame with one row per trading day and columns for each feature.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_log_returns(close: pd.Series, periods: list[int] = (1, 5, 21)) -> pd.DataFrame:
    """Compute multi-period log returns from adjusted close prices.

    log_return(p) = ln(P_t / P_{t-p})

    Args:
        close: Adjusted close prices (pandas Series, index = date).
        periods: Lookback periods in trading days.

    Returns:
        DataFrame with columns log_ret_1d, log_ret_5d, log_ret_21d.
    """
    result = pd.DataFrame(index=close.index)
    for p in periods:
        col = f"log_ret_{p}d"
        # ponytail: shift(p) gives clean lookback; first p rows will be NaN
        result[col] = np.log(close / close.shift(p))
    return result


def compute_moving_averages(close: pd.Series, windows: list[int] = (5, 10, 20, 50)) -> pd.DataFrame:
    """Compute simple moving averages.

    Returns:
        DataFrame with columns ma_5, ma_10, ma_20, ma_50.
    """
    result = pd.DataFrame(index=close.index)
    for w in windows:
        result[f"ma_{w}"] = close.rolling(window=w).mean()
    return result


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index (RSI).

    RSI = 100 - (100 / (1 + RS))
    RS = average_gain / average_loss over the period

    Uses Wilder's smoothed method (simple moving average of gains/losses).

    Returns:
        Series with RSI values (0-100), NaN for first `period` rows.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # ponytail: Wilder's smoothing uses simple rolling mean. Wilders (exponential)
    # would need a custom implementation. Simple MA is sufficient for V1.
    rs = avg_gain / avg_loss.replace(0, np.nan)  # Avoid div by zero
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Compute MACD (Moving Average Convergence Divergence).

    MACD line = EMA(fast) - EMA(slow)
    Signal line = EMA(MACD, signal)
    Histogram = MACD - Signal

    Returns:
        DataFrame with columns macd, macd_signal, macd_hist.
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal_line

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": macd_signal_line,
        "macd_hist": macd_hist,
    }, index=close.index)


def compute_rolling_volatility(close: pd.Series, period: int = 30) -> pd.Series:
    """Compute rolling standard deviation of daily log returns.

    sigma_30d = std(log_returns, window=30)

    Returns:
        Series with rolling volatility values.
    """
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window=period).std()


def compute_volatility_rank(close: pd.Series, period: int = 252) -> pd.Series:
    """Compute the percentile rank of current volatility within a 1-year window.

    vol_rank = percentile(sigma_30d, lookback=252)

    This normalises volatility across tickers with different base volatility levels.

    Returns:
        Series with percentile ranks (0-1), NaN for first `period` rows.
    """
    vol = compute_rolling_volatility(close, period=30)
    # Rolling percentile rank via expanding window for early data, rolling for full window
    # ponytail: simple rank-based percentile. For large datasets, use scipy.stats.rankdata.
    rank = vol.rolling(window=period, min_periods=period).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 0 else np.nan,
        raw=False,
    )
    return rank


def standardise_features(
    df: pd.DataFrame,
    means: pd.Series | None = None,
    stds: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Z-score standardise all feature columns.

    For training: pass means=None, stds=None to compute from data.
    For inference: pass the training means and stds.

    Returns:
        (standardised_df, means, stds) tuple.
    """
    feature_cols = [c for c in df.columns if not c.startswith("label") and c != "ticker"]
    if means is None:
        means = df[feature_cols].mean()
        stds = df[feature_cols].std()
        # Replace zero std with 1 to avoid division by zero
        stds = stds.replace(0, 1.0)

    result = df.copy()
    result[feature_cols] = (df[feature_cols] - means) / stds
    return result, means, stds


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 13 technical indicators from OHLCV data.

    Args:
        df: DataFrame with columns: date, adjusted_close (at minimum).
             May also have open, high, low, close, volume (unused in V1).

    Returns:
        DataFrame with date index and 13 feature columns plus ticker column.
        Rows with NaN features are kept (dataset.py handles padding).

    Feature columns:
        log_ret_1d, log_ret_5d, log_ret_21d, ma_5, ma_10, ma_20, ma_50,
        rsi_14, macd, macd_signal, macd_hist, vol_30d, vol_rank
    """
    close = df["adjusted_close"].copy()

    features = pd.DataFrame(index=df.index)

    # Log returns
    for col, series in compute_log_returns(close).items():
        features[col] = series

    # Moving averages
    for col, series in compute_moving_averages(close).items():
        features[col] = series

    # RSI
    features["rsi_14"] = compute_rsi(close)

    # MACD
    macd_df = compute_macd(close)
    features["macd"] = macd_df["macd"]
    features["macd_signal"] = macd_df["macd_signal"]
    features["macd_hist"] = macd_df["macd_hist"]

    # Volatility
    features["vol_30d"] = compute_rolling_volatility(close)
    features["vol_rank"] = compute_volatility_rank(close)

    # Preserve ticker if present
    if "ticker" in df.columns:
        features["ticker"] = df["ticker"]

    return features
```

**Why:** Pure pandas/numpy functions. Each indicator computed independently for testability. Standardisation z-scores per feature across all tickers' data. All NaN edge cases handled (first N rows NaN for rolling computations).

**Edge cases:**

- Fewer than 60 days of data -> all features NaN -> ticker excluded from training
- Constant price (no movement) -> zero std -> replaced with 1.0 to avoid NaN
- Single NaN in middle of series -> rolling windows propagate NaN

---

#### Step 2.3 - Adaptive Labeling

**File:** backend/ml/labeling.py
**Action:** Compute UP/FLAT/DOWN labels using adaptive volatility threshold.

```python
"""
Adaptive labeling for directional forecasting.

Labels are computed per-ticker using a rolling volatility threshold,
normalising across tickers with different base volatility levels.

Label definitions:
    FLAT  if |log_return| < 0.5 * sigma_30d
    UP    if log_return >= 0.5 * sigma_30d
    DOWN  if log_return <= -0.5 * sigma_30d
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_adaptive_labels(
    close: pd.Series,
    vol_lookback: int = 30,
    threshold_mult: float = 0.5,
    forecast_horizon: int = 1,
) -> pd.Series:
    """Compute UP/FLAT/DOWN labels using adaptive volatility threshold.

    The label for day t is based on the log return from day t to t+forecast_horizon,
    classified using the rolling volatility at day t.

    Args:
        close: Adjusted close prices (pandas Series).
        vol_lookback: Window for rolling volatility calculation.
        threshold_mult: Multiplier on sigma for the FLAT band.
        forecast_horizon: Days ahead to predict (default 1).

    Returns:
        Series with labels: 0=DOWN, 1=FLAT, 2=UP. NaN for last horizon+s
        rows where future return is unavailable.
    """
    # Forward log return over forecast_horizon
    forward_ret = np.log(close.shift(-forecast_horizon) / close)

    # Rolling volatility of daily log returns
    daily_log_ret = np.log(close / close.shift(1))
    rolling_vol = daily_log_ret.rolling(window=vol_lookback).std()

    # Adaptive threshold
    threshold = rolling_vol * threshold_mult

    # Classify
    labels = pd.Series(index=close.index, dtype=float)
    labels[forward_ret.abs() < threshold] = 1.0  # FLAT
    labels[forward_ret >= threshold] = 2.0        # UP
    labels[forward_ret <= -threshold] = 0.0       # DOWN

    # NaN where forward_ret or threshold is NaN
    labels[forward_ret.isna() | threshold.isna()] = np.nan

    return labels


def compute_label_distribution(labels: pd.Series) -> dict[str, float]:
    """Compute class distribution of labels.

    Returns:
        Dict mapping class name to proportion (0-1).
    """
    valid = labels.dropna()
    if len(valid) == 0:
        return {"DOWN": 0.0, "FLAT": 0.0, "UP": 0.0}

    total = len(valid)
    return {
        "DOWN": float((valid == 0).sum() / total),
        "FLAT": float((valid == 1).sum() / total),
        "UP": float((valid == 2).sum() / total),
    }
```

**Why:** Adaptive thresholds normalise across volatile and stable tickers. A 1% move is significant for a stable stock but noise for a volatile one. Label distribution can be monitored to detect class imbalance.

**Edge cases:**

- No price movement -> sigma=0, threshold=0 -> all labels are UP or DOWN (degenerate). Handled by standardisation: vol_rank = 0.5, vol_30d = 0 -> UP/DOWN split based on sign of tiny moves.
- Forward return unavailable (last row) -> NaN label -> excluded from dataset.
- All prices identical -> sigma=0, threshold=0 -> all labels resolve to UP/DOWN. Not a realistic scenario for liquid equities.

---

#### Step 2.4 - Sequence Dataset

**File:** backend/ml/dataset.py
**Action:** PyTorch Dataset for sliding window sequences with chronological split.

```python
"""
SequenceDataset and chronological split utilities.

Each sample is a (features, label, ticker_idx) tuple where:
    features: (SEQUENCE_LENGTH, N_FEATURES) tensor
    label: int (0=DOWN, 1=FLAT, 2=UP)
    ticker_idx: int (embedding index)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch
from torch.utils.data import Dataset


class SequenceDataset(Dataset):
    """PyTorch Dataset for sliding window sequences.

    Takes a merged DataFrame with columns: ticker_idx, features..., label.
    Creates (SEQUENCE_LENGTH, N_FEATURES) windows with their labels.

    Args:
        sequences: numpy array of shape (N, SEQUENCE_LENGTH, N_FEATURES).
        labels: numpy array of shape (N,) with class labels.
        ticker_idxs: numpy array of shape (N,) with ticker embedding indices.
    """

    def __init__(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        ticker_idxs: np.ndarray,
    ) -> None:
        assert len(sequences) == len(labels) == len(ticker_idxs), \
            f"Length mismatch: {len(sequences)} vs {len(labels)} vs {len(ticker_idxs)}"
        self.sequences = torch.tensor(sequences, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.long)
        self.ticker_idxs = torch.tensor(ticker_idxs, dtype=torch.long)

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return self.sequences[idx], self.labels[idx], self.ticker_idxs[idx]


def create_sliding_windows(
    df_normalised: np.ndarray,
    labels: np.ndarray,
    ticker_idxs: np.ndarray,
    sequence_length: int = 30,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create sliding windows from a normalised feature matrix.

    For a ticker with T time steps and F features, creates T - sequence_length + 1
    windows of shape (sequence_length, F).

    Args:
        df_normalised: numpy array (T, F) of z-scored features.
        labels: numpy array (T,) of labels for each time step.
        ticker_idxs: numpy array (T,) of ticker embedding indices.
        sequence_length: Number of time steps per window.

    Returns:
        (sequences, window_labels, window_ticker_idxs) tuple.
        sequences shape: (N, sequence_length, F)
        window_labels shape: (N,)
        window_ticker_idxs shape: (N,)
    """
    T = df_normalised.shape[0]
    if T < sequence_length:
        # ponytail: return empty arrays for short tickers instead of padding
        return (
            np.empty((0, sequence_length, df_normalised.shape[1])),
            np.empty((0,)),
            np.empty((0,)),
        )

    sequences = np.lib.stride_tricks.sliding_window_view(
        df_normalised, window_shape=(sequence_length, df_normalised.shape[1])
    )
    # sliding_window_view returns shape (T-sL+1, sL, F)
    # Extract labels: the label at the END of each window (t+1)
    window_labels = labels[sequence_length - 1:]
    window_ticker_idxs = ticker_idxs[sequence_length - 1:]

    # Remove windows where the label is NaN
    valid_mask = ~np.isnan(window_labels)
    sequences = sequences[valid_mask]
    window_labels = window_labels[valid_mask]
    window_ticker_idxs = window_ticker_idxs[valid_mask]

    return sequences, window_labels.astype(np.int64), window_ticker_idxs.astype(np.int64)


def chronological_split(
    sequences: np.ndarray,
    labels: np.ndarray,
    ticker_idxs: np.ndarray,
    train_frac: float = 0.7,
    val_frac: float = 0.15,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
]:
    """Chronological train/val/test split across ALL tickers (global).

    All sequences from all tickers are merged and sorted by time
    (they already are if concatenated chronologically). Split is
    purely sequential - no random shuffle.

    Args:
        sequences: (N, seq_len, n_features) array.
        labels: (N,) array.
        ticker_idxs: (N,) array.
        train_frac: Fraction for training.
        val_frac: Fraction for validation.

    Returns:
        (train, val, test) where each is (sequences, labels, ticker_idxs).
    """
    N = len(sequences)
    train_end = int(N * train_frac)
    val_end = train_end + int(N * val_frac)

    train = (sequences[:train_end], labels[:train_end], ticker_idxs[:train_end])
    val = (sequences[train_end:val_end], labels[train_end:val_end], ticker_idxs[train_end:val_end])
    test = (sequences[val_end:], labels[val_end:], ticker_idxs[val_end:])

    return train, val, test
```

**Why:** numpy.lib.stride_tricks.sliding_window_view creates windows without copying data (memory efficient). Chronological split respects time ordering - critical for time series to avoid look-ahead bias.

**Edge cases:**

- Ticker with fewer than sequence_length days -> empty arrays, excluded from dataloader
- Last sequence_length-1 labels are NaN (no forward return) -> filtered by valid_mask
- Uneven split at boundaries -> val_end may be same as train_end if dataset is tiny

---

#### Step 2.5 - Utilities

**File:** backend/ml/utils.py
**Action:** Device detection, seed setting, ticker vocabulary builder.

```python
"""
Shared utilities for the ML module.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
import torch


UNK_IDX = 0  # Unknown ticker embedding index


def get_device() -> torch.device:
    """Detect and return the best available device.

    Priority: CUDA > MPS > CPU.

    Returns:
        torch.device instance.
    """
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def set_seed(seed: int = 42) -> None:
    """Set random seed for reproducibility across all libraries.

    Args:
        seed: Random seed value.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    # ponytail: deterministic algorithms can be slower; only enable if
    # bit-exact reproducibility is needed. torch.use_deterministic_algorithms(True)


def build_ticker_vocabulary(
    tickers: list[str],
    unk_token: str = "<UNK>",
) -> tuple[dict[str, int], int]:
    """Build ticker-to-index vocabulary for entity embeddings.

    Index 0 is reserved for UNK (unknown ticker).

    Args:
        tickers: List of ticker symbols (e.g., ["AAPL", "MSFT", "GOOGL"]).
        unk_token: Token for unknown tickers.

    Returns:
        (vocab dict mapping ticker -> index, vocab_size including UNK).
    """
    vocab = {unk_token: UNK_IDX}
    for ticker in sorted(set(tickers)):
        if ticker not in vocab:
            vocab[ticker] = len(vocab)
    return vocab, len(vocab)


def get_ticker_idx(ticker: str, vocab: dict[str, int]) -> int:
    """Get embedding index for a ticker, falling back to UNK.

    Args:
        ticker: Ticker symbol.
        vocab: Ticker-to-index vocabulary.

    Returns:
        Embedding index (UNK_IDX if ticker not in vocab).
    """
    return vocab.get(ticker.upper(), UNK_IDX)
```

**Why:** Device detection with MPS support for Apple Silicon. Seed setting for reproducibility. UNK-reserved index 0 so unseen tickers map to a learned embedding.

---

#### Step 2.6 - Feature/Label/Dataset Tests

**File:** backend/tests/test_ml/**init**.py
**Action:** Empty module marker.

```python
"""ML module unit tests - no DB access required."""
```

---

**File:** backend/tests/test_ml/test_features.py
**Action:** ~15 tests covering all feature functions and edge cases.

```python
"""Tests for ml/features.py - technical indicator computation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def simple_close() -> pd.Series:
    """Monotonically increasing close prices (10 days)."""
    return pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])


@pytest.fixture
def volatile_close() -> pd.Series:
    """Close prices with both up and down moves (252 days)."""
    np.random.seed(42)
    # Random walk starting at 100
    returns = np.random.normal(0, 0.02, 252)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.Series(prices)


class TestLogReturns:
    def test_log_returns_positive_trend(self, simple_close: pd.Series) -> None:
        from ml.features import compute_log_returns

        result = compute_log_returns(simple_close)
        # 10 days -> 9 log returns (shift(1) makes first row NaN)
        assert result["log_ret_1d"].iloc[1] == pytest.approx(np.log(101 / 100), rel=1e-6)
        assert result["log_ret_1d"].isna().iloc[0]
        assert result["log_ret_5d"].isna().iloc[:5].all()

    def test_log_returns_empty(self) -> None:
        from ml.features import compute_log_returns

        result = compute_log_returns(pd.Series([], dtype=float))
        assert len(result) == 0

    def test_log_returns_single_value(self) -> None:
        from ml.features import compute_log_returns

        result = compute_log_returns(pd.Series([100.0]))
        assert result["log_ret_1d"].isna().iloc[0]


class TestMovingAverages:
    def test_sma_basic(self) -> None:
        from ml.features import compute_moving_averages

        close = pd.Series([1, 2, 3, 4, 5, 6])
        result = compute_moving_averages(close, windows=[3])
        # First 2 rows NaN, row index 2 = (1+2+3)/3 = 2
        assert result["ma_3"].iloc[2] == 2.0
        assert result["ma_3"].iloc[3] == 3.0

    def test_sma_not_enough_data(self) -> None:
        from ml.features import compute_moving_averages

        close = pd.Series([1, 2])
        result = compute_moving_averages(close, windows=[5])
        assert result["ma_5"].isna().all()


class TestRSI:
    def test_rsi_bounds(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_rsi

        rsi = compute_rsi(volatile_close)
        # RSI should be between 0 and 100
        assert rsi.dropna().between(0, 100).all()

    def test_rsi_all_up(self) -> None:
        from ml.features import compute_rsi

        close = pd.Series(np.linspace(100, 200, 30))
        rsi = compute_rsi(close, period=14)
        # All up moves -> RSI should be 100
        assert rsi.dropna().iloc[-1] == pytest.approx(100.0, rel=1e-4)

    def test_rsi_all_down(self) -> None:
        from ml.features import compute_rsi

        close = pd.Series(np.linspace(200, 100, 30))
        rsi = compute_rsi(close, period=14)
        # All down moves -> RSI should be 0
        assert rsi.dropna().iloc[-1] == pytest.approx(0.0, abs=1e-4)


class TestMACD:
    def test_macd_output_shape(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_macd

        result = compute_macd(volatile_close)
        assert list(result.columns) == ["macd", "macd_signal", "macd_hist"]
        assert len(result) == len(volatile_close)

    def test_macd_zero_for_flat(self) -> None:
        from ml.features import compute_macd

        close = pd.Series([100.0] * 50)
        result = compute_macd(close)
        # With flat prices, MACD should be ~0
        assert result["macd"].dropna().iloc[-1] == pytest.approx(0.0, abs=1e-6)


class TestRollingVolatility:
    def test_volatility_constant(self) -> None:
        from ml.features import compute_rolling_volatility

        close = pd.Series([100.0] * 50)
        vol = compute_rolling_volatility(close, period=10)
        # No movement -> zero volatility
        assert vol.dropna().iloc[-1] == 0.0

    def test_volatility_shape(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_rolling_volatility

        vol = compute_rolling_volatility(volatile_close, period=30)
        assert len(vol) == len(volatile_close)
        assert vol.isna().sum() == 30  # First 30 NaN


class TestStandardise:
    def test_standardise_basic(self) -> None:
        from ml.features import standardise_features

        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]})
        result, means, stds = standardise_features(df)
        assert result["a"].mean() == pytest.approx(0.0, abs=1e-6)
        assert result["a"].std() == pytest.approx(1.0, abs=1e-6)

    def test_standardise_with_inference_means(self) -> None:
        from ml.features import standardise_features

        df_train = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        _, means, stds = standardise_features(df_train)

        df_infer = pd.DataFrame({"a": [6, 7, 8]})
        result, _, _ = standardise_features(df_infer, means, stds)
        # 6 -> (6-3)/1.58
        expected = (6 - means["a"]) / stds["a"]
        assert result["a"].iloc[0] == pytest.approx(float(expected), abs=1e-6)

    def test_standardise_zero_std(self) -> None:
        from ml.features import standardise_features

        df = pd.DataFrame({"a": [5, 5, 5]})
        result, _, stds = standardise_features(df)
        assert stds["a"] == 1.0  # Replaced zero std
        assert result["a"].iloc[0] == 0.0  # All values at mean


class TestAllFeatures:
    def test_compute_all_features(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_all_features

        df = pd.DataFrame({"adjusted_close": volatile_close})
        result = compute_all_features(df)
        expected_cols = [
            "log_ret_1d", "log_ret_5d", "log_ret_21d",
            "ma_5", "ma_10", "ma_20", "ma_50",
            "rsi_14", "macd", "macd_signal", "macd_hist",
            "vol_30d", "vol_rank",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_compute_all_features_short_series(self) -> None:
        from ml.features import compute_all_features

        df = pd.DataFrame({"adjusted_close": [100.0, 101.0]})
        result = compute_all_features(df)
        # All features should be NaN with only 2 data points
        assert result.iloc[:, :-1].isna().all().all()
```

Total: ~15 tests covering log returns, moving averages, RSI, MACD, rolling volatility, standardisation, and the all-features orchestrator.

---

**File:** backend/tests/test_ml/test_labeling.py
**Action:** ~10 tests for adaptive labeling.

```python
"""Tests for ml/labeling.py - adaptive UP/FLAT/DOWN labeling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestAdaptiveLabels:
    def test_up_trend(self) -> None:
        from ml.labeling import compute_adaptive_labels

        # Monotonically increasing prices
        close = pd.Series(np.linspace(100, 150, 100))
        labels = compute_adaptive_labels(close)
        # Most labels should be UP (2)
        assert (labels.dropna() == 2).sum() > (labels.dropna() == 0).sum()

    def test_down_trend(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series(np.linspace(150, 100, 100))
        labels = compute_adaptive_labels(close)
        assert (labels.dropna() == 0).sum() > (labels.dropna() == 2).sum()

    def test_flat_market(self) -> None:
        from ml.labeling import compute_adaptive_labels

        # Mostly flat with small noise
        np.random.seed(42)
        close = pd.Series(100 + np.random.normal(0, 0.5, 200))
        labels = compute_adaptive_labels(close, threshold_mult=2.0)
        # With wide threshold, most labels should be FLAT (1)
        flat_ratio = (labels.dropna() == 1).sum() / labels.dropna().shape[0]
        assert flat_ratio > 0.5

    def test_threshold_zero(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series([100.0] * 50)
        labels = compute_adaptive_labels(close, threshold_mult=0.0)
        # Zero threshold -> UP or DOWN (no FLAT)
        assert (labels.dropna() == 1).sum() == 0

    def test_all_nan_returns_nan(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series([100.0])
        labels = compute_adaptive_labels(close)
        # Single point -> no forward return -> all NaN
        assert labels.isna().all()

    def test_random_walk_distribution(self) -> None:
        from ml.labeling import compute_adaptive_labels, compute_label_distribution

        np.random.seed(42)
        returns = np.random.normal(0, 0.01, 1000)
        close = pd.Series(100 * np.exp(np.cumsum(returns)))
        labels = compute_adaptive_labels(close)
        dist = compute_label_distribution(labels)
        # Random walk should have roughly balanced UP/DOWN with some FLAT
        assert 0.2 < dist["FLAT"] < 0.6
        assert 0.2 < dist["UP"] < 0.6
        assert 0.2 < dist["DOWN"] < 0.6

    def test_highly_volatile_has_fewer_flat(self) -> None:
        from ml.labeling import compute_adaptive_labels, compute_label_distribution

        np.random.seed(42)
        returns = np.random.normal(0, 0.05, 1000)  # 5% daily vol
        close = pd.Series(100 * np.exp(np.cumsum(returns)))
        labels = compute_adaptive_labels(close, threshold_mult=0.5)
        dist = compute_label_distribution(labels)
        assert dist["FLAT"] < 0.4
```

---

**File:** backend/tests/test_ml/test_dataset.py
**Action:** ~10 tests for SequenceDataset and chronological split.

```python
"""Tests for ml/dataset.py - sequence dataset and chronological split."""

from __future__ import annotations

import numpy as np
import pytest
import torch


class TestSequenceDataset:
    def test_basic_creation(self) -> None:
        from ml.dataset import SequenceDataset

        sequences = np.random.randn(100, 30, 13).astype(np.float32)
        labels = np.random.randint(0, 3, size=100)
        ticker_idxs = np.zeros(100, dtype=np.int64)

        ds = SequenceDataset(sequences, labels, ticker_idxs)
        assert len(ds) == 100
        seq, lbl, tidx = ds[0]
        assert seq.shape == (30, 13)
        assert isinstance(lbl, torch.Tensor)
        assert lbl.item() in (0, 1, 2)

    def test_empty_dataset(self) -> None:
        from ml.dataset import SequenceDataset

        ds = SequenceDataset(
            np.empty((0, 30, 13)), np.empty((0,)), np.empty((0,))
        )
        assert len(ds) == 0

    def test_length_mismatch_raises(self) -> None:
        from ml.dataset import SequenceDataset

        with pytest.raises(AssertionError):
            SequenceDataset(
                np.random.randn(10, 30, 13),
                np.random.randint(0, 3, size=5),  # Wrong length
                np.zeros(10),
            )


class TestSlidingWindows:
    def test_basic_windows(self) -> None:
        from ml.dataset import create_sliding_windows

        # 50 days, 3 features
        data = np.random.randn(50, 3)
        labels = np.random.randint(0, 3, size=50).astype(float)
        ticker_idxs = np.zeros(50)

        seqs, labs, tidxs = create_sliding_windows(data, labels, ticker_idxs, sequence_length=30)

        # 50 - 30 + 1 = 21 windows (assuming no NaN labels)
        assert len(seqs) <= 21
        assert seqs.shape[1:] == (30, 3)

    def test_too_short_returns_empty(self) -> None:
        from ml.dataset import create_sliding_windows

        data = np.random.randn(20, 3)
        labels = np.ones(20)
        ticker_idxs = np.zeros(20)

        seqs, _, _ = create_sliding_windows(data, labels, ticker_idxs, sequence_length=30)
        assert len(seqs) == 0

    def test_nan_labels_filtered(self) -> None:
        from ml.dataset import create_sliding_windows

        data = np.random.randn(50, 3)
        labels = np.full(50, np.nan)  # All NaN
        ticker_idxs = np.zeros(50)

        seqs, labs, _ = create_sliding_windows(data, labels, ticker_idxs, sequence_length=30)
        assert len(seqs) == 0
        assert len(labs) == 0


class TestChronologicalSplit:
    def test_split_ratios(self) -> None:
        from ml.dataset import chronological_split

        sequences = np.random.randn(1000, 30, 13)
        labels = np.random.randint(0, 3, size=1000)
        ticker_idxs = np.zeros(1000)

        train, val, test = chronological_split(sequences, labels, ticker_idxs)

        assert len(train[0]) == 700
        assert len(val[0]) == 150
        assert len(test[0]) == 150

    def test_split_preserves_order(self) -> None:
        from ml.dataset import chronological_split

        # Labels are sequential integers - split should preserve order
        labels = np.arange(1000)
        sequences = np.random.randn(1000, 30, 13)
        ticker_idxs = np.zeros(1000)

        train, val, test = chronological_split(sequences, labels, ticker_idxs)

        assert train[1][0] == 0
        assert train[1][-1] == 699
        assert val[1][0] == 700
        assert test[1][0] == 850

    def test_small_dataset(self) -> None:
        from ml.dataset import chronological_split

        sequences = np.random.randn(10, 30, 13)
        labels = np.arange(10)
        ticker_idxs = np.zeros(10)

        train, val, test = chronological_split(sequences, labels, ticker_idxs)
        # Fractions of 10: train=7, val=1, test=2 (or train=7, val=2, test=1 depending on rounding)
        assert len(train[0]) + len(val[0]) + len(test[0]) == 10
```

---

### Round 3 - LSTM Model Definition

**Goal:** GlobalLSTM PyTorch module, training loop with early stopping, and evaluation suite (directional accuracy, F1, simulated Sharpe).

**Files to create:** 3 (ml/model.py, ml/train.py, ml/evaluate.py)
**Files to modify:** 0

---

#### Step 3.1 - GlobalLSTM Model

**File:** backend/ml/model.py
**Action:** Define the GlobalLSTM PyTorch module with entity embeddings.

```python
"""
GlobalLSTM - multi-ticker LSTM model with entity embeddings.

Architecture:
    TickerEmbedding(vocab_size, embed_dim=16) -> concat with features
    -> FeatureProjection(n_features + embed_dim, hidden_dim)
    -> LSTM(hidden_dim, hidden_size=128, num_layers=2, dropout=0.3, batch_first=True)
    -> Classifier(128, 3) -> softmax

The model learns per-ticker embedding vectors to capture ticker-specific
price dynamics while sharing LSTM weights across all tickers.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class GlobalLSTM(nn.Module):
    """Global multi-ticker LSTM with entity embeddings.

    Args:
        n_features: Number of technical indicator features per time step.
        vocab_size: Number of tickers in vocabulary (including UNK).
        embed_dim: Entity embedding dimension.
        hidden_dim: LSTM hidden state dimension.
        n_layers: Number of LSTM layers.
        dropout: Dropout probability (applied between LSTM layers and after LSTM).
        n_classes: Number of output classes (default 3: DOWN, FLAT, UP).
        unk_idx: Index reserved for unknown tickers (default 0).
    """

    def __init__(
        self,
        n_features: int,
        vocab_size: int,
        embed_dim: int = 16,
        hidden_dim: int = 128,
        n_layers: int = 2,
        dropout: float = 0.3,
        n_classes: int = 3,
        unk_idx: int = 0,
    ) -> None:
        super().__init__()

        self.n_features = n_features
        self.embed_dim = embed_dim
        self.hidden_dim = hidden_dim
        self.unk_idx = unk_idx

        # Inference metadata (set by load() from checkpoint)
        self._vocab: dict[str, int] = {}
        self._feature_means: Optional[np.ndarray] = None
        self._feature_stds: Optional[np.ndarray] = None

        # Ticker entity embedding
        self.ticker_embedding = nn.Embedding(
            num_embeddings=vocab_size,
            embedding_dim=embed_dim,
            padding_idx=unk_idx,
        )

        # Project concatenated features + embedding to hidden_dim
        input_size = n_features + embed_dim
        self.feature_projection = nn.Linear(input_size, hidden_dim)

        # LSTM
        self.lstm = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=hidden_dim,
            num_layers=n_layers,
            dropout=dropout if n_layers > 1 else 0.0,
            batch_first=True,
            bidirectional=False,
        )

        # Post-LSTM dropout
        self.dropout = nn.Dropout(dropout)

        # Classifier
        self.classifier = nn.Linear(hidden_dim, n_classes)

    def forward(
        self,
        features: torch.Tensor,
        ticker_idxs: torch.Tensor,
    ) -> torch.Tensor:
        """Forward pass.

        Args:
            features: (batch_size, seq_len, n_features) tensor.
            ticker_idxs: (batch_size,) tensor of ticker embedding indices.

        Returns:
            (batch_size, n_classes) logits (NOT softmaxed - use with CrossEntropyLoss).
        """
        batch_size, seq_len, _ = features.shape

        # Get ticker embeddings: (batch_size, embed_dim)
        ticker_embeds = self.ticker_embedding(ticker_idxs)  # (B, embed_dim)

        # Expand to match sequence length: (batch_size, seq_len, embed_dim)
        ticker_embeds = ticker_embeds.unsqueeze(1).expand(-1, seq_len, -1)

        # Concatenate features with ticker embedding
        combined = torch.cat([features, ticker_embeds], dim=-1)  # (B, seq_len, n_features + embed_dim)

        # Project to hidden_dim
        projected = self.feature_projection(combined)  # (B, seq_len, hidden_dim)
        projected = F.relu(projected)

        # LSTM
        lstm_out, (h_n, _) = self.lstm(projected)  # lstm_out: (B, seq_len, hidden_dim)

        # Use the last hidden state from the top LSTM layer
        # h_n shape: (n_layers, B, hidden_dim) -> take last layer
        last_hidden = h_n[-1]  # (B, hidden_dim)

        # Dropout + classifier
        last_hidden = self.dropout(last_hidden)
        logits = self.classifier(last_hidden)  # (B, n_classes)

        return logits

    @torch.no_grad()
    def predict_proba(self, features: torch.Tensor, ticker_idxs: torch.Tensor) -> torch.Tensor:
        """Return softmax probabilities.

        Args:
            features: (batch_size, seq_len, n_features) tensor.
            ticker_idxs: (batch_size,) tensor.

        Returns:
            (batch_size, n_classes) probability tensor.
        """
        logits = self.forward(features, ticker_idxs)
        return F.softmax(logits, dim=-1)

    def save(
        self,
        path: str,
        vocab: Optional[dict[str, int]] = None,
        feature_means: Optional[np.ndarray] = None,
        feature_stds: Optional[np.ndarray] = None,
    ) -> None:
        """Save model state dict and config metadata.

        Args:
            path: Path to save the .pt file.
            vocab: Ticker-to-index vocabulary for embedding lookup at inference.
            feature_means: Per-feature means for z-score standardisation (inverse of training).
            feature_stds: Per-feature stds for z-score standardisation.
        """
        payload: dict = {
            "state_dict": self.state_dict(),
            "n_features": self.n_features,
            "embed_dim": self.ticker_embedding.embedding_dim,
            "hidden_dim": self.hidden_dim,
            "n_layers": self.lstm.num_layers,
            "dropout": self.lstm.dropout,
            "n_classes": self.classifier.out_features,
            "vocab_size": self.ticker_embedding.num_embeddings,
            "unk_idx": self.unk_idx,
        }
        if vocab is not None:
            payload["vocab"] = vocab
        if feature_means is not None:
            payload["feature_means"] = feature_means
        if feature_stds is not None:
            payload["feature_stds"] = feature_stds
        torch.save(payload, path)

    @classmethod
    def load(cls, path: str, device: torch.device | None = None) -> GlobalLSTM:
        """Load model from saved state dict.

        Args:
            path: Path to the .pt file.
            device: Target device. If None, uses saved tensor's device.

        Returns:
            Loaded GlobalLSTM instance with ``vocab``, ``feature_means``,
            ``feature_stds`` attributes set if present in checkpoint.
        """
        checkpoint = torch.load(path, map_location=device, weights_only=True)
        model = cls(
            n_features=checkpoint["n_features"],
            vocab_size=checkpoint["vocab_size"],
            embed_dim=checkpoint["embed_dim"],
            hidden_dim=checkpoint["hidden_dim"],
            n_layers=checkpoint["n_layers"],
            dropout=checkpoint["dropout"],
            n_classes=checkpoint["n_classes"],
            unk_idx=checkpoint["unk_idx"],
        )
        model.load_state_dict(checkpoint["state_dict"])

        # Load optional metadata for inference standardisation
        model._vocab = checkpoint.get("vocab", {})
        model._feature_means = checkpoint.get("feature_means")
        model._feature_stds = checkpoint.get("feature_stds")

        model.eval()
        return model
```

**Why:** Entity embeddings concatenated with features at each time step (not just at the beginning). This lets the LSTM use ticker identity throughout the sequence. `save`/`load` class methods encapsulate serialisation. `predict_proba` is `@torch.no_grad()` for inference efficiency.

**Model size estimate:** ~2MB for 55 tickers x 16-dim embeddings (3.5K params) + LSTM weights (128*128*4*2 + 128*16 ~135K) + classifier (128\*3 = 384). Total ~140K parameters.

---

#### Step 3.2 - Training Loop

**File:** backend/ml/train.py
**Action:** Training loop with Adam, weighted cross-entropy, early stopping.

```python
"""
Training loop for GlobalLSTM.

Key features:
    - Adam optimiser with weight decay
    - Weighted cross-entropy loss (handles class imbalance)
    - Early stopping with patience 10
    - Per-epoch logging of loss and accuracy
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)


def compute_class_weights(labels: torch.Tensor, n_classes: int = 3) -> torch.Tensor:
    """Compute class weights inversely proportional to class frequencies.

    weight[c] = total_samples / (n_classes * samples_in_class[c])

    Args:
        labels: (N,) tensor of class labels.
        n_classes: Number of classes.

    Returns:
        (n_classes,) tensor of class weights.
    """
    class_counts = torch.bincount(labels, minlength=n_classes).float()
    total = class_counts.sum()
    weights = total / (n_classes * class_counts)
    # Replace inf (empty class) with 1.0
    weights[~torch.isfinite(weights)] = 1.0
    return weights


def train_epoch(
    model: GlobalLSTM,
    dataloader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    """Train for one epoch.

    Args:
        model: GlobalLSTM instance.
        dataloader: Training DataLoader.
        criterion: Loss function (weighted cross-entropy).
        optimizer: Adam optimizer.
        device: torch.device.

    Returns:
        Mean training loss for the epoch.
    """
    model.train()
    total_loss = 0.0
    num_batches = 0

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        labels = labels.to(device)
        ticker_idxs = ticker_idxs.to(device)

        optimizer.zero_grad()
        logits = model(features, ticker_idxs)
        loss = criterion(logits, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)  # ponytail: gradient clipping prevents exploding gradients
        optimizer.step()

        total_loss += loss.item()
        num_batches += 1

    return total_loss / max(num_batches, 1)


@torch.no_grad()
def validate(
    model: GlobalLSTM,
    dataloader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    """Validate the model.

    Args:
        model: GlobalLSTM instance.
        dataloader: Validation DataLoader.
        criterion: Loss function.
        device: torch.device.

    Returns:
        (validation_loss, accuracy) tuple.
    """
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        labels = labels.to(device)
        ticker_idxs = ticker_idxs.to(device)

        logits = model(features, ticker_idxs)
        loss = criterion(logits, labels)
        total_loss += loss.item()

        preds = logits.argmax(dim=-1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    avg_loss = total_loss / max(len(dataloader), 1)
    accuracy = correct / max(total, 1)
    return avg_loss, accuracy


def train(
    model: GlobalLSTM,
    train_loader: DataLoader,
    val_loader: DataLoader,
    n_epochs: int = ML_CONFIG.EPOCHS,
    lr: float = ML_CONFIG.LEARNING_RATE,
    weight_decay: float = ML_CONFIG.WEIGHT_DECAY,
    patience: int = ML_CONFIG.PATIENCE,
    min_delta: float = ML_CONFIG.MIN_DELTA,
    device: torch.device | None = None,
) -> dict[str, list[float]]:
    """Full training loop with early stopping.

    Args:
        model: GlobalLSTM instance.
        train_loader: Training DataLoader.
        val_loader: Validation DataLoader.
        n_epochs: Maximum number of epochs.
        lr: Learning rate.
        weight_decay: AdamW weight decay.
        patience: Early stopping patience.
        min_delta: Minimum validation loss improvement.
        device: Target device. Auto-detected if None.

    Returns:
        Dict with keys: train_losses, val_losses, val_accuracies, best_epoch.
    """
    if device is None:
        from ml.utils import get_device
        device = get_device()

    model = model.to(device)

    # Compute class weights from training data
    all_labels = []
    for _, labels, _ in train_loader:
        all_labels.append(labels)
    train_labels = torch.cat(all_labels)
    class_weights = compute_class_weights(train_labels).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=lr,
        weight_decay=weight_decay,
    )

    history = {
        "train_losses": [],
        "val_losses": [],
        "val_accuracies": [],
    }

    best_val_loss = float("inf")
    best_epoch = -1
    patience_counter = 0

    for epoch in range(1, n_epochs + 1):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = validate(model, val_loader, criterion, device)

        history["train_losses"].append(train_loss)
        history["val_losses"].append(val_loss)
        history["val_accuracies"].append(val_acc)

        logger.info(
            "Epoch %d/%d - train_loss: %.4f, val_loss: %.4f, val_acc: %.4f",
            epoch, n_epochs, train_loss, val_loss, val_acc,
        )

        # Early stopping check
        if val_loss < best_val_loss - min_delta:
            best_val_loss = val_loss
            best_epoch = epoch
            patience_counter = 0
            # Save best model state
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info(
                    "Early stopping at epoch %d (best epoch %d, val_loss %.4f)",
                    epoch, best_epoch, best_val_loss,
                )
                break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
    model.to(device)

    history["best_epoch"] = best_epoch
    return history
```

**Why:** Weighted cross-entropy handles FLAT-dominant class imbalance. Early stopping prevents overfitting. Gradient clipping stabilises training. AdamW (decoupled weight decay) is standard practice over plain Adam.

---

#### Step 3.3 - Evaluation Suite

**File:** backend/ml/evaluate.py
**Action:** Directional accuracy, per-class F1, confusion matrix, simulated Sharpe ratio.

```python
"""
Evaluation metrics for the GlobalLSTM model.

All functions operate on numpy arrays (not tensors) for easy logging and plotting.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import torch
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)


@torch.no_grad()
def evaluate(
    model: GlobalLSTM,
    dataloader: DataLoader,
    device: torch.device,
) -> dict[str, Any]:
    """Comprehensive evaluation on a DataLoader.

    Args:
        model: GlobalLSTM instance.
        dataloader: DataLoader (typically test set).
        device: torch.device.

    Returns:
        Dict with keys: accuracy, per_class_f1, confusion_matrix,
        directional_accuracy, simulated_sharpe.
    """
    model.eval()
    all_preds: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    all_probs: list[np.ndarray] = []

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        ticker_idxs = ticker_idxs.to(device)

        logits = model(features, ticker_idxs)
        probs = torch.softmax(logits, dim=-1)
        preds = logits.argmax(dim=-1)

        all_preds.append(preds.cpu().numpy())
        all_labels.append(labels.numpy())
        all_probs.append(probs.cpu().numpy())

    preds = np.concatenate(all_preds)
    labels = np.concatenate(all_labels)
    probs = np.concatenate(all_probs)

    # Directional accuracy (overall)
    accuracy = float((preds == labels).mean())

    # Per-class metrics
    per_class_f1 = _compute_per_class_f1(labels, preds, n_classes=ML_CONFIG.N_CLASSES)
    confusion_matrix = _compute_confusion_matrix(labels, preds, n_classes=ML_CONFIG.N_CLASSES)

    # Directional accuracy (UP vs DOWN only, ignoring FLAT)
    directional_mask = (labels != 1)
    if directional_mask.sum() > 0:
        directional_acc = float((preds[directional_mask] == labels[directional_mask]).mean())
    else:
        directional_acc = 0.0

    # Simulated Sharpe
    simulated_sharpe = compute_simulated_sharpe(labels, preds, probs)

    return {
        "accuracy": accuracy,
        "directional_accuracy": directional_acc,
        "per_class_f1": per_class_f1,
        "confusion_matrix": confusion_matrix.tolist(),
        "simulated_sharpe": simulated_sharpe,
        "total_samples": len(labels),
    }


def _compute_per_class_f1(
    labels: np.ndarray,
    preds: np.ndarray,
    n_classes: int = 3,
) -> dict[str, float]:
    """Compute per-class F1 score.

    Uses sklearn.metrics.f1_score with 'macro' average.

    Returns:
        Dict mapping class name to F1 score.
    """
    from sklearn.metrics import f1_score

    f1 = f1_score(labels, preds, average=None, labels=np.arange(n_classes))
    return {
        f"{ML_CONFIG.CLASS_NAMES[i]}": float(f1[i])
        for i in range(n_classes)
        if i < len(f1)
    }


def _compute_confusion_matrix(
    labels: np.ndarray,
    preds: np.ndarray,
    n_classes: int = 3,
) -> np.ndarray:
    """Compute confusion matrix.

    Returns:
        (n_classes, n_classes) numpy array.
    """
    from sklearn.metrics import confusion_matrix

    return confusion_matrix(labels, preds, labels=np.arange(n_classes))


def compute_simulated_sharpe(
    labels: np.ndarray,
    preds: np.ndarray,
    probs: np.ndarray,
    annual_factor: float = 252.0,
) -> float:
    """Compute Sharpe ratio from a simulated trading strategy.

    Strategy: Long the ticker when model predicts UP (class 2).
    Flat (cash) when model predicts FLAT (class 1) or DOWN (class 0).

    Daily return from strategy:
        - If prediction is UP: return = market_return (from labels)
        - If prediction is FLAT/DOWN: return = 0 (cash)

    Since we're simulating from historical labels, we use the actual
    market return when the strategy is long.

    Args:
        labels: True class labels (0=DOWN, 1=FLAT, 2=UP).
        preds: Predicted class labels.
        probs: Softmax probabilities (unused in V1 - for future confidence-based sizing).
        annual_factor: Number of trading days per year.

    Returns:
        Annualised Sharpe ratio. Returns 0.0 if std is 0.
    """
    # Strategy daily returns: long when prediction is UP, cash otherwise
    # For simulation, we need actual daily returns. Convert labels back:
    # UP (2) -> positive return, DOWN (0) -> negative return, FLAT (1) -> zero
    # Use approximate returns from label severity
    # ponytail: uses label as proxy for return magnitude. Replace with actual
    # log returns when available from the dataset for more accurate simulation.

    # Binary signal: 1.0 when long (pred=UP), 0.0 when flat (pred=FLAT/DOWN)
    signal = (preds == 2).astype(float)

    # Actual market returns: approximate from labels
    # DOWN -> -1%, FLAT -> 0%, UP -> +1% (normalised approximation)
    # ponytail: 1% per directional day is a rough proxy. Replace with actual
    # forward returns from the feature engineering pipeline for accuracy.
    market_returns = np.where(labels == 2, 0.01, np.where(labels == 0, -0.01, 0.0))

    # Strategy returns
    strategy_returns = signal * market_returns

    mean_return = float(np.mean(strategy_returns))
    std_return = float(np.std(strategy_returns))

    if std_return == 0.0:
        return 0.0

    # Annualise
    annualised_return = mean_return * annual_factor
    annualised_std = std_return * np.sqrt(annual_factor)
    sharpe = annualised_return / annualised_std

    return float(sharpe)


def plot_confusion_matrix(
    cm: np.ndarray,
    class_names: tuple[str, ...] = ML_CONFIG.CLASS_NAMES,
    save_path: str = "/tmp/confusion_matrix.png",
) -> str:
    """Plot and save confusion matrix.

    Args:
        cm: (n_classes, n_classes) confusion matrix.
        class_names: Class label names.
        save_path: File path to save the plot.

    Returns:
        Path to the saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
    ax.figure.colorbar(im, ax=ax)

    ax.set(
        xticks=np.arange(len(class_names)),
        yticks=np.arange(len(class_names)),
        xticklabels=class_names,
        yticklabels=class_names,
        xlabel="Predicted",
        ylabel="True",
    )

    # Rotate tick labels
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    # Display values
    for i in range(len(class_names)):
        for j in range(len(class_names)):
            ax.text(j, i, str(int(cm[i, j])), ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black")

    plt.tight_layout()
    plt.savefig(save_path, dpi=100, bbox_inches="tight")
    plt.close()
    return save_path


def plot_loss_curves(
    train_losses: list[float],
    val_losses: list[float],
    save_path: str = "/tmp/loss_curves.png",
) -> str:
    """Plot and save training and validation loss curves.

    Args:
        train_losses: List of training losses per epoch.
        val_losses: List of validation losses per epoch.
        save_path: File path to save the plot.

    Returns:
        Path to the saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    epochs = range(1, len(train_losses) + 1)
    ax.plot(epochs, train_losses, label="Training Loss", marker="o")
    ax.plot(epochs, val_losses, label="Validation Loss", marker="s")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Loss")
    ax.set_title("Training and Validation Loss")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=100, bbox_inches="tight")
    plt.close()
    return save_path
```

**Why:** sklearn for robust F1 and confusion matrix computation. Simulated Sharpe converts the classification output to a trading signal for a more interpretable metric than raw accuracy. All plotting uses `matplotlib.use("Agg")` for headless environments.

---

#### Step 3.4 - Model and Evaluation Tests

**File:** backend/tests/test_ml/test_model.py
**Action:** ~10 tests for GlobalLSTM forward pass, saving/loading, UNK handling.

```python
"""Tests for ml/model.py - GlobalLSTM architecture."""

from __future__ import annotations

import tempfile

import pytest
import torch


@pytest.fixture
def model() -> torch.nn.Module:
    from ml.model import GlobalLSTM
    return GlobalLSTM(
        n_features=13,
        vocab_size=56,  # 55 tickers + UNK
        embed_dim=16,
        hidden_dim=128,
        n_layers=2,
        dropout=0.3,
        n_classes=3,
        unk_idx=0,
    )


class TestGlobalLSTM:
    def test_forward_shape(self, model: torch.nn.Module) -> None:
        batch_size, seq_len = 32, 30
        features = torch.randn(batch_size, seq_len, 13)
        ticker_idxs = torch.zeros(batch_size, dtype=torch.long)

        logits = model(features, ticker_idxs)
        assert logits.shape == (batch_size, 3)

    def test_predict_proba(self, model: torch.nn.Module) -> None:
        features = torch.randn(16, 30, 13)
        ticker_idxs = torch.zeros(16, dtype=torch.long)

        probs = model.predict_proba(features, ticker_idxs)
        assert probs.shape == (16, 3)
        # Probabilities should sum to 1
        assert torch.allclose(probs.sum(dim=-1), torch.ones(16))

    def test_different_ticker_embeddings(self) -> None:
        from ml.model import GlobalLSTM
        model = GlobalLSTM(n_features=13, vocab_size=10, embed_dim=8, hidden_dim=32, n_layers=1, dropout=0.0, n_classes=3)

        features = torch.randn(4, 30, 13)
        ticker_idxs = torch.tensor([0, 1, 2, 3])

        logits = model(features, ticker_idxs)
        # Different tickers should produce different outputs (different embeddings)
        assert not torch.allclose(logits[0], logits[1])

    def test_unk_embedding(self, model: torch.nn.Module) -> None:
        features = torch.randn(2, 30, 13)
        ticker_idxs = torch.tensor([0, 999])  # UNK and unknown index > vocab_size

        # Should not crash - embedding will use padding_idx for 0,
        # and out-of-vocab indices will be clamped by embedding layer
        with pytest.raises(RuntimeError):
            model(features, ticker_idxs)

    def test_save_and_load(self, model: torch.nn.Module) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pt") as f:
            model.save(f.name)

            loaded = model.__class__.load(f.name)
            assert isinstance(loaded, model.__class__)
            assert loaded.n_features == 13
            assert loaded.hidden_dim == 128

            # Forward pass should work on loaded model
            features = torch.randn(8, 30, 13)
            ticker_idxs = torch.zeros(8, dtype=torch.long)
            logits = loaded(features, ticker_idxs)
            assert logits.shape == (8, 3)

    def test_single_sample(self, model: torch.nn.Module) -> None:
        features = torch.randn(1, 30, 13)
        ticker_idxs = torch.zeros(1, dtype=torch.long)

        logits = model(features, ticker_idxs)
        assert logits.shape == (1, 3)
        assert not torch.isnan(logits).any()

    def test_gradient_flow(self, model: torch.nn.Module) -> None:
        features = torch.randn(16, 30, 13, requires_grad=True)
        ticker_idxs = torch.zeros(16, dtype=torch.long)

        logits = model(features, ticker_idxs)
        loss = logits.sum()
        loss.backward()

        # All parameters should have gradients
        for name, param in model.named_parameters():
            assert param.grad is not None, f"No gradient for {name}"
```

**File:** backend/tests/test_ml/test_evaluate.py
**Action:** ~15 tests for evaluation metrics.

```python
"""Tests for ml/evaluate.py - evaluation metrics."""

from __future__ import annotations

import numpy as np
import pytest


class TestDirectionalAccuracy:
    def test_perfect_prediction(self) -> None:
        from ml.evaluate import evaluate
        # We'll test the underlying functions directly
        from ml.evaluate import _compute_confusion_matrix

        labels = np.array([0, 1, 2, 0, 1, 2])
        preds = np.array([0, 1, 2, 0, 1, 2])
        cm = _compute_confusion_matrix(labels, preds)
        assert np.trace(cm) == 6  # All diagonal

    def test_all_wrong(self) -> None:
        from ml.evaluate import _compute_confusion_matrix

        labels = np.array([0, 1, 2])
        preds = np.array([1, 2, 0])
        cm = _compute_confusion_matrix(labels, preds)
        assert np.trace(cm) == 0  # Nothing on diagonal

    def test_accuracy_calculation(self) -> None:
        from ml.evaluate import evaluate as evaluate_fn

        # We test _compute_per_class_f1 separately
        from ml.evaluate import _compute_per_class_f1

        labels = np.array([0, 0, 1, 1, 2, 2])
        preds = np.array([0, 0, 1, 1, 2, 2])
        f1 = _compute_per_class_f1(labels, preds)
        assert f1["DOWN"] == pytest.approx(1.0)
        assert f1["FLAT"] == pytest.approx(1.0)
        assert f1["UP"] == pytest.approx(1.0)


class TestPerClassF1:
    def test_imbalanced(self) -> None:
        from ml.evaluate import _compute_per_class_f1

        # Mostly DOWN (class 0), few UP (class 2)
        labels = np.array([0, 0, 0, 0, 0, 2, 2])
        preds = np.array([0, 0, 0, 0, 0, 0, 2])  # Missed one UP
        f1 = _compute_per_class_f1(labels, preds)
        assert f1["DOWN"] > 0.9
        assert f1["UP"] < 1.0  # Not perfect

    def test_single_class(self) -> None:
        from ml.evaluate import _compute_per_class_f1

        labels = np.array([1, 1, 1])
        preds = np.array([1, 1, 1])
        f1 = _compute_per_class_f1(labels, preds)
        assert f1["FLAT"] == pytest.approx(1.0)


class TestSimulatedSharpe:
    def test_perfect_up_strategy(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        # Always predict UP, always correct
        labels = np.array([2, 2, 2])  # True UP
        preds = np.array([2, 2, 2])
        probs = np.ones((3, 3)) / 3

        sharpe = compute_simulated_sharpe(labels, preds, probs)
        assert sharpe > 0

    def test_always_wrong_strategy(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        # Always predict DOWN when UP is true -> always flat (no signal)
        labels = np.array([2, 2, 2])
        preds = np.array([0, 0, 0])
        probs = np.ones((3, 3)) / 3

        sharpe = compute_simulated_sharpe(labels, preds, probs)
        assert sharpe == 0.0  # No long positions

    def test_mixed_strategy(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        labels = np.array([2, 0, 2, 0])  # UP, DOWN, UP, DOWN
        preds = np.array([2, 2, 2, 2])  # Always predict UP
        probs = np.ones((4, 3)) / 3

        sharpe = compute_simulated_sharpe(labels, preds, probs)
        # Long on UP and DOWN days -> mixed returns
        assert isinstance(sharpe, float)


class TestPlotFunctions:
    def test_confusion_matrix_plot(self) -> None:
        from ml.evaluate import plot_confusion_matrix

        cm = np.array([[10, 2, 1], [3, 15, 2], [1, 2, 20]])
        path = plot_confusion_matrix(cm)
        assert path.endswith(".png")

    def test_loss_curves_plot(self) -> None:
        from ml.evaluate import plot_loss_curves

        path = plot_loss_curves(
            [0.8, 0.6, 0.4, 0.3],
            [0.9, 0.7, 0.5, 0.4],
        )
        assert path.endswith(".png")
```

---

### Round 4 - MLflow Integration & Training Pipeline

**Goal:** MLflow run management, config logging, metric logging, model registration, and the orchestrator pipeline that ties everything together.

**Files to create:** 2 (ml/mlflow_manager.py, ml/pipeline.py)
**Files to modify:** 0

---

#### Step 4.1 - MLflow Manager

**File:** backend/ml/mlflow_manager.py
**Action:** MLflow run management, model logging, champion registration.

```python
"""
MLflow integration for experiment tracking and model registry.

Handles:
    - Run creation and management
    - Hyperparameter and metric logging
    - Artifact logging (loss curves, confusion matrix)
    - Model saving and registration
    - Champion model alias management
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import mlflow
import mlflow.pytorch

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)


class MLflowManager:
    """Manages MLflow runs and model registry operations."""

    def __init__(self, experiment_name: str = "stocklens_lstm") -> None:
        mlflow.set_tracking_uri(ML_CONFIG.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(experiment_name)
        self.experiment_name = experiment_name
        self.active_run: Optional[mlflow.ActiveRun] = None

    def start_run(self, run_name: Optional[str] = None) -> str:
        """Start a new MLflow run.

        Args:
            run_name: Optional human-readable run name.

        Returns:
            MLflow run ID.
        """
        self.active_run = mlflow.start_run(run_name=run_name)
        run_id = self.active_run.info.run_id
        logger.info("MLflow run started", run_id=run_id)
        return run_id

    def end_run(self) -> None:
        """End the active MLflow run."""
        if self.active_run:
            mlflow.end_run()
            logger.info("MLflow run ended")
            self.active_run = None

    def log_params(self, params: dict[str, Any]) -> None:
        """Log hyperparameters to the active run."""
        mlflow.log_params(params)

    def log_metrics(self, metrics: dict[str, float], step: Optional[int] = None) -> None:
        """Log metrics to the active run.

        Args:
            metrics: Dict of metric name to value.
            step: Optional step (epoch) number.
        """
        mlflow.log_metrics(metrics, step=step)

    def log_artifact(self, local_path: str, artifact_path: Optional[str] = None) -> None:
        """Log a local file as an artifact.

        Args:
            local_path: Path to local file.
            artifact_path: Optional subdirectory within artifact store.
        """
        mlflow.log_artifact(local_path, artifact_path=artifact_path)

    def log_model(
        self,
        model: GlobalLSTM,
        artifact_path: str = "model",
        registered_model_name: str = "GlobalLSTM",
    ) -> tuple[str, str]:
        """Log the PyTorch model to MLflow and register it.

        Args:
            model: Trained GlobalLSTM instance.
            artifact_path: Path within MLflow artifacts.
            registered_model_name: Name for Model Registry.

        Returns:
            (run_id, model_version) tuple.
        """
        # Log model using mlflow.pytorch
        mlflow.pytorch.log_model(
            pytorch_model=model,
            artifact_path=artifact_path,
            registered_model_name=registered_model_name,
            requirements_file=None,
        )

        # Get the registered model version
        client = mlflow.tracking.MlflowClient()
        model_version = client.get_latest_versions(
            registered_model_name,
            stages=["None"],
        )
        version = model_version[0].version if model_version else "1"

        run_id = self.active_run.info.run_id if self.active_run else "unknown"
        return run_id, version

    def set_champion_alias(self, model_name: str = "GlobalLSTM", version: str = "1") -> None:
        """Set the 'champion' alias on a model version.

        Args:
            model_name: Registered model name.
            version: Model version string.
        """
        client = mlflow.tracking.MlflowClient()
        client.set_registered_model_alias(model_name, "champion", version)
        logger.info("Champion alias set", model_name=model_name, version=version)

    def save_champion_to_disk(self, model: GlobalLSTM) -> str:
        """Save champion model to the shared volume for backend inference.

        Uses atomic write (temp file + rename) so the backend never reads
        a partially-written model file.

        Args:
            model: Trained GlobalLSTM instance.

        Returns:
            Path to the saved model file.
        """
        import os
        import tempfile

        save_dir = Path(ML_CONFIG.MODEL_ARTIFACT_DIR)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(save_dir / "model.pt")

        # Write to a temp file in the same directory, then atomic rename
        fd, tmp_path = tempfile.mkstemp(dir=str(save_dir), suffix=".pt.tmp")
        try:
            model.save(tmp_path)
            os.fsync(fd)  # flush OS buffer
            os.replace(tmp_path, save_path)  # atomic on POSIX, near-atomic on macOS
        finally:
            os.close(fd)
            # Clean up temp file if rename failed
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        logger.info("Champion model saved to disk (atomic)", path=save_path)
        return save_path
```

**Why:** Separate manager class encapsulates MLflow boilerplate. `set_champion_alias` marks the best model for the backend to find. `save_champion_to_disk` writes to the shared volume that the backend mounts.

---

#### Step 4.2 - Training Pipeline (Orchestrator)

**File:** backend/ml/pipeline.py
**Action:** Full orchestrator: fetch OHLCV -> features -> dataset -> train -> evaluate -> log -> register.

```python
"""
Training pipeline orchestrator.

Run via: docker compose run ml python -m ml.pipeline

Flow:
    1. Fetch OHLCV for training tickers from PostgreSQL
    2. Compute features and labels per ticker
    3. Build ticker vocabulary
    4. Merge into global dataset with chronological ordering
    5. Train/val/test split (chronological 70/15/15)
    6. Create DataLoaders
    7. Train GlobalLSTM
    8. Evaluate on test set
    9. Log everything to MLflow
    10. Register champion, save to disk, record in model_registry DB
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta

import numpy as np
import torch
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.dataset import SequenceDataset, chronological_split, create_sliding_windows
from ml.evaluate import evaluate, plot_confusion_matrix, plot_loss_curves
from ml.features import compute_all_features, standardise_features
from ml.labeling import compute_adaptive_labels
from ml.mlflow_manager import MLflowManager
from ml.model import GlobalLSTM
from ml.train import train
from ml.utils import build_ticker_vocabulary, get_device, set_seed

logger = logging.getLogger(__name__)


async def fetch_ohlcv_for_tickers(tickers: list[str]) -> dict[str, np.ndarray]:
    """Fetch OHLCV data from PostgreSQL for all training tickers.

    Each ticker's data is returned as a structured numpy array with columns:
        date, open, high, low, close, adjusted_close, volume

    Args:
        tickers: List of ticker symbols.

    Returns:
        Dict mapping ticker -> numpy structured array.
    """
    import asyncpg

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    start_date = date.today() - timedelta(days=int(ML_CONFIG.OHLCV_YEARS * 365.25))

    conn = await asyncpg.connect(dsn)
    try:
        result: dict[str, np.ndarray] = {}
        for ticker in tickers:
            rows = await conn.fetch(
                """
                SELECT date, open, high, low, close, adjusted_close, volume
                FROM ohlcv_prices
                WHERE ticker = $1 AND date >= $2
                ORDER BY date ASC
                """,
                ticker,
                start_date,
            )
            if len(rows) < ML_CONFIG.MIN_OHLCV_DAYS:
                logger.warning("Skipping %s: only %d days of data", ticker, len(rows))
                continue

            # Convert to numpy structured array
            dtype = [
                ("date", "datetime64[D]"),
                ("open", "f8"), ("high", "f8"), ("low", "f8"),
                ("close", "f8"), ("adjusted_close", "f8"), ("volume", "i8"),
            ]
            arr = np.array(
                [(r["date"], float(r["open"] or 0), float(r["high"] or 0),
                  float(r["low"] or 0), float(r["close"] or 0),
                  float(r["adjusted_close"] or 0), int(r["volume"] or 0))
                 for r in rows],
                dtype=dtype,
            )
            if len(arr) >= ML_CONFIG.MIN_OHLCV_DAYS:
                result[ticker] = arr

    finally:
        await conn.close()

    logger.info("Fetched OHLCV data", tickers=len(result))
    return result


def prepare_global_dataset(
    ohlcv_data: dict[str, np.ndarray],
    vocab: dict[str, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Prepare global dataset from per-ticker OHLCV data.

    For each ticker:
        1. Compute features (technical indicators)
        2. Compute labels (adaptive UP/FLAT/DOWN)
        3. Create sliding windows
        4. Assign ticker index

    All tickers are merged into a single chronologically-ordered dataset.

    Args:
        ohlcv_data: Dict mapping ticker -> OHLCV structured array.
        vocab: Ticker-to-index vocabulary.

    Returns:
        (global_sequences, global_labels, global_ticker_idxs) tuple.
        Returns empty arrays if no data passes filtering.
    """
    all_sequences: list[np.ndarray] = []
    all_labels_list: list[np.ndarray] = []
    all_ticker_idxs: list[np.ndarray] = []

    import pandas as pd

    for ticker, arr in ohlcv_data.items():
        # Convert to DataFrame for feature computation
        df = pd.DataFrame({
            "adjusted_close": arr["adjusted_close"],
            "ticker": ticker,
        })

        # Compute features
        features_df = compute_all_features(df)

        # Compute labels
        close_series = pd.Series(arr["adjusted_close"])
        labels = compute_adaptive_labels(
            close_series,
            vol_lookback=ML_CONFIG.VOL_LOOKBACK,
            threshold_mult=ML_CONFIG.THRESHOLD_MULT,
        )

        # Convert to numpy for sliding windows
        feature_values = features_df.drop(columns=["ticker"], errors="ignore").values.astype(np.float32)
        label_values = labels.values.astype(np.float64)
        ticker_idx = vocab.get(ticker, 0)

        # Standardise features (z-score)
        # Compute ticker-level mean/std for its own normalisation
        feature_means = np.nanmean(feature_values, axis=0)
        feature_stds = np.nanstd(feature_values, axis=0)
        feature_stds[feature_stds == 0] = 1.0
        feature_values = (feature_values - feature_means) / feature_stds

        # Replace remaining NaN with 0 (after z-score, NaN becomes 0 at boundaries)
        feature_values = np.nan_to_num(feature_values, nan=0.0)

        # Create sliding windows
        sequences, seq_labels, seq_ticker_idxs = create_sliding_windows(
            feature_values,
            label_values,
            np.full(len(label_values), ticker_idx),
            sequence_length=ML_CONFIG.SEQUENCE_LENGTH,
        )

        if len(sequences) > 0:
            all_sequences.append(sequences)
            all_labels_list.append(seq_labels)
            all_ticker_idxs.append(seq_ticker_idxs)

    if not all_sequences:
        return (
            np.empty((0, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES)),
            np.empty((0,)),
            np.empty((0,)),
        )

    # Merge all tickers
    global_sequences = np.concatenate(all_sequences, axis=0)
    global_labels = np.concatenate(all_labels_list, axis=0)
    global_ticker_idxs = np.concatenate(all_ticker_idxs, axis=0)

    return global_sequences, global_labels, global_ticker_idxs


async def run_pipeline() -> dict[str, float]:
    """Run the full training pipeline.

    Returns:
        Dict of test set metrics.
    """
    set_seed(42)
    device = get_device()
    logger.info("Starting ML pipeline", device=str(device))

    # 1. Fetch OHLCV data
    logger.info("Fetching OHLCV data for %d tickers", len(ML_CONFIG.TRAINING_TICKERS))
    ohlcv_data = await fetch_ohlcv_for_tickers(ML_CONFIG.TRAINING_TICKERS)
    if not ohlcv_data:
        logger.error("No OHLCV data fetched - aborting")
        return {"error": 1.0}

    # 2. Build ticker vocabulary
    tickers_with_data = list(ohlcv_data.keys())
    vocab, vocab_size = build_ticker_vocabulary(tickers_with_data)
    logger.info("Ticker vocabulary built", vocab_size=vocab_size, tickers=len(tickers_with_data))

    # 3. Prepare global dataset
    global_sequences, global_labels, global_ticker_idxs = prepare_global_dataset(ohlcv_data, vocab)
    logger.info("Global dataset prepared", samples=len(global_sequences))

    if len(global_sequences) < 100:
        logger.error("Too few samples (%d) - aborting", len(global_sequences))
        return {"error": 1.0}

    # 4. Chronological split
    train_data, val_data, test_data = chronological_split(
        global_sequences, global_labels, global_ticker_idxs,
        train_frac=ML_CONFIG.TRAIN_SPLIT,
        val_frac=ML_CONFIG.VAL_SPLIT,
    )
    logger.info(
        "Dataset split - train: %d, val: %d, test: %d",
        len(train_data[0]), len(val_data[0]), len(test_data[0]),
    )

    # 5. Create DataLoaders
    train_ds = SequenceDataset(*train_data)
    val_ds = SequenceDataset(*val_data)
    test_ds = SequenceDataset(*test_data)

    # ponytail: num_workers=0 for CPU training. Set >0 for GPU with appropriate
    # multiprocessing context.
    train_loader = DataLoader(train_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
    val_loader = DataLoader(val_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)

    # 6. Initialise model
    model = GlobalLSTM(
        n_features=ML_CONFIG.N_FEATURES,
        vocab_size=vocab_size,
        embed_dim=ML_CONFIG.EMBED_DIM,
        hidden_dim=ML_CONFIG.HIDDEN_DIM,
        n_layers=ML_CONFIG.N_LAYERS,
        dropout=ML_CONFIG.DROPOUT,
        n_classes=ML_CONFIG.N_CLASSES,
    )
    logger.info("Model initialised", params=sum(p.numel() for p in model.parameters()))

    # 7. Start MLflow run
    mlflow_mgr = MLflowManager()
    run_id = mlflow_mgr.start_run(run_name=f"global_lstm_v1_{len(tickers_with_data)}tickers")

    # Log config params
    mlflow_mgr.log_params({
        "n_features": ML_CONFIG.N_FEATURES,
        "vocab_size": vocab_size,
        "embed_dim": ML_CONFIG.EMBED_DIM,
        "hidden_dim": ML_CONFIG.HIDDEN_DIM,
        "n_layers": ML_CONFIG.N_LAYERS,
        "dropout": ML_CONFIG.DROPOUT,
        "sequence_length": ML_CONFIG.SEQUENCE_LENGTH,
        "batch_size": ML_CONFIG.BATCH_SIZE,
        "learning_rate": ML_CONFIG.LEARNING_RATE,
        "weight_decay": ML_CONFIG.WEIGHT_DECAY,
        "patience": ML_CONFIG.PATIENCE,
        "n_tickers": len(tickers_with_data),
        "train_samples": len(train_ds),
        "val_samples": len(val_ds),
        "test_samples": len(test_ds),
    })

    # 8. Train
    history = train(model, train_loader, val_loader, device=device, n_epochs=ML_CONFIG.EPOCHS)

    # Log epoch-level metrics
    for epoch in range(len(history["train_losses"])):
        mlflow_mgr.log_metrics({
            "train_loss": history["train_losses"][epoch],
            "val_loss": history["val_losses"][epoch],
            "val_accuracy": history["val_accuracies"][epoch],
        }, step=epoch + 1)

    # 9. Evaluate on test set
    test_metrics = evaluate(model, test_loader, device)
    logger.info("Test metrics: %s", test_metrics)

    # Log test metrics
    mlflow_mgr.log_metrics({
        "test_accuracy": test_metrics["accuracy"],
        "test_directional_accuracy": test_metrics["directional_accuracy"],
        "test_simulated_sharpe": test_metrics["simulated_sharpe"],
    })

    for class_name, f1 in test_metrics["per_class_f1"].items():
        mlflow_mgr.log_metrics({f"f1_{class_name.lower()}": f1})

    # 10. Plot and log artifacts
    cm_path = plot_confusion_matrix(np.array(test_metrics["confusion_matrix"]))
    mlflow_mgr.log_artifact(cm_path, artifact_path="evaluation")

    loss_path = plot_loss_curves(history["train_losses"], history["val_losses"])
    mlflow_mgr.log_artifact(loss_path, artifact_path="training")

    # 11. Log model and register
    _, model_version = mlflow_mgr.log_model(model)
    mlflow_mgr.set_champion_alias(version=model_version)

    # 12. Save champion to shared volume for backend inference
    champion_path = mlflow_mgr.save_champion_to_disk(model)

    # 13. Record in model_registry DB
    await _record_in_db(run_id, model_version, test_metrics)

    mlflow_mgr.end_run()

    logger.info("Pipeline complete", champion_path=champion_path, run_id=run_id)
    return test_metrics


async def _record_in_db(
    run_id: str,
    model_version: str,
    metrics: dict,
) -> None:
    """Record the champion model in the model_registry DB table."""
    import asyncpg
    import json

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    conn = await asyncpg.connect(dsn)
    async with conn.transaction():
        # Remove existing champion for this model type
        await conn.execute(
            "UPDATE model_registry SET alias = NULL WHERE alias = 'champion'"
        )
        # Insert new champion
        await conn.execute(
            """
            INSERT INTO model_registry (ticker, mlflow_run_id, model_version, alias, metrics)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            None,  # Global model - no specific ticker
            run_id,
            model_version,
            "champion",
            json.dumps(metrics),
        )
    await conn.close()
    logger.info("Champion recorded in model_registry", run_id=run_id)


def main() -> None:
    """Entry point for the training pipeline.

    Usage: docker compose run ml python -m ml.pipeline
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    import asyncio

    metrics = asyncio.run(run_pipeline())

    if "error" in metrics:
        sys.exit(1)

    print("\n=== Training Complete ===")
    print(f"Test Directional Accuracy: {metrics.get('directional_accuracy', 0):.2%}")
    print(f"Test Simulated Sharpe: {metrics.get('simulated_sharpe', 0):.2f}")
    print(f"Per-class F1: {metrics.get('per_class_f1', {})}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

**Why:** Single orchestrator that ties everything together. `asyncio.run()` for async DB operations. MLflow logging at each step. Champion model saved to shared volume and recorded in model_registry DB.

---

### Round 5 - Production Predict Endpoint

**Goal:** FastAPI prediction endpoint with lifespan-loaded model, Redis caching, and proper error handling. Tests for the endpoint.

**Files to create:** 4 (src/prediction/**init**.py, src/prediction/schemas.py, src/prediction/service.py, src/prediction/router.py)
**Files to modify:** 3 (src/main.py, src/config.py, backend/Dockerfile)

---

#### Step 5.1 - Prediction Schemas

**File:** backend/src/prediction/**init**.py
**Action:** Empty module marker.

```python
"""
Prediction module - LSTM directional forecasting endpoint.

Loads the champion GlobalLSTM model at startup and serves predictions
via GET /predict/{ticker} with Redis 6h caching.
"""

from __future__ import annotations
```

**File:** backend/src/prediction/schemas.py
**Action:** Pydantic models for prediction request/response.

```python
"""
Pydantic schemas for the prediction endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.types import DecimalAsFloat


class PredictionResponse(BaseModel):
    """Response for a directional forecast prediction."""

    ticker: str
    direction: str = Field(description="Predicted direction: UP, FLAT, or DOWN")
    confidence: DecimalAsFloat = Field(description="Confidence in the predicted class (0-1)")
    probabilities: dict[str, DecimalAsFloat] = Field(
        description="Softmax probabilities for each class: {DOWN, FLAT, UP}"
    )
    model_version: str = Field(description="MLflow model version used for prediction")
    cached: bool = Field(False, description="Whether the result was served from cache")
    predicted_at: datetime


class PredictionErrorResponse(BaseModel):
    """Error response for prediction failures."""

    detail: str
    code: str = Field(description="Error code: NO_DATA, MODEL_NOT_LOADED, INFERENCE_ERROR, UNKNOWN_TICKER")
```

**Why:** `model_version` enables frontend to display which model generated the prediction. `cached` flag for debugging. `probabilities` dict gives full softmax output for confidence-based UIs.

---

#### Step 5.2 - Prediction Service

**File:** backend/src/prediction/service.py
**Action:** Loads champion model, computes features, runs inference. Singleton pattern loaded at startup.

```python
"""
Prediction service - model loading, feature computation, inference.

Loaded once at FastAPI startup via lifespan and reused across requests.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch

from ml.config import ML_CONFIG as ml_config
from ml.features import compute_all_features, standardise_features
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)

CLASS_NAMES = ("DOWN", "FLAT", "UP")


class PredictionService:
    """Singleton prediction service loaded at startup.

    Loads the champion GlobalLSTM model from the shared artifacts volume
    and performs inference on demand.
    """

    def __init__(self) -> None:
        self.model: Optional[GlobalLSTM] = None
        self.model_version: str = "0"
        self.device = torch.device("cpu")  # Inference always on CPU
        self._feature_means: Optional[np.ndarray] = None
        self._feature_stds: Optional[np.ndarray] = None
        self._vocab: Optional[dict[str, int]] = None

    def load_model(self, model_path: str = "/model_artifacts/champion/model.pt") -> bool:
        """Load champion model from disk.

        Args:
            model_path: Path to the saved model .pt file.

        Returns:
            True if model loaded successfully, False otherwise.
        """
        path = Path(model_path)
        if not path.exists():
            logger.warning("No champion model found at %s", model_path)
            return False

        try:
            self.model = GlobalLSTM.load(str(path), device=self.device)
            self.model.to(self.device)
            self.model.eval()
            logger.info("Champion model loaded from %s", model_path)
            return True
        except Exception as exc:
            logger.exception("Failed to load champion model: %s", exc)
            return False

    def is_loaded(self) -> bool:
        """Check if model is loaded and ready."""
        return self.model is not None

    def _compute_features(self, ohlcv_rows: list[dict]) -> Optional[torch.Tensor]:
        """Compute 30-day feature window from OHLCV data and standardise.

        Uses the global feature means/stds stored in the model checkpoint
        during training. Without standardisation, the model receives
        non-normalized inputs and produces degraded predictions.

        Args:
            ohlcv_rows: List of OHLCV dicts from market/repository.py.

        Returns:
            (1, 30, n_features) tensor ready for model input, or None if
            insufficient data.
        """
        if len(ohlcv_rows) < ml_config.SEQUENCE_LENGTH + 30:
            # Need at least 30 extra days for feature lookback
            logger.warning(
                "Insufficient OHLCV data: %d rows, need %d",
                len(ohlcv_rows),
                ml_config.SEQUENCE_LENGTH + 30,
            )
            return None

        # Convert to DataFrame
        df = pd.DataFrame(ohlcv_rows).sort_values("date")
        close = df["adjusted_close"].astype(float)

        # Compute features
        features_df = compute_all_features(pd.DataFrame({"adjusted_close": close}))

        # Take the last SEQUENCE_LENGTH rows
        feature_values = features_df.values[-ml_config.SEQUENCE_LENGTH:].astype(np.float32)

        # Handle NaN (shouldn't happen with 60+ days of data, but safeguard)
        feature_values = np.nan_to_num(feature_values, nan=0.0)

        # Apply z-score standardisation using training distribution params
        if self.model is not None and self.model._feature_means is not None and self.model._feature_stds is not None:
            means = self.model._feature_means
            stds = self.model._feature_stds
            feature_values = (feature_values - means) / stds
        else:
            # Fallback: per-batch standardisation (less accurate but prevents raw input)
            logger.warning("No stored feature means/stds - applying per-batch standardisation")
            batch_mean = np.nanmean(feature_values, axis=0)
            batch_std = np.nanstd(feature_values, axis=0)
            batch_std[batch_std == 0] = 1.0
            feature_values = (feature_values - batch_mean) / batch_std

        # Convert to tensor
        tensor = torch.tensor(feature_values, dtype=torch.float32).unsqueeze(0)  # (1, 30, N_FEATURES)
        return tensor

    def predict(self, ticker: str, ohlcv_rows: list[dict]) -> Optional[dict]:
        """Run prediction for a single ticker.

        Args:
            ticker: Ticker symbol (for embedding lookup).
            ohlcv_rows: List of OHLCV dicts (90+ days).

        Returns:
            Dict with keys: direction, confidence, probabilities, model_version.
            None if prediction cannot be made.
        """
        if self.model is None:
            logger.error("Model not loaded - cannot predict")
            return None

        # Get ticker embedding index from model's stored vocabulary
        # The vocab is loaded from the checkpoint in GlobalLSTM.load()
        # and includes all training tickers + UNK. Unknown tickers fall
        # back to UNK embedding (index 0).
        vocab = getattr(self.model, "_vocab", {})
        ticker_idx_val = vocab.get(ticker.upper(), 0)  # 0 = UNK_IDX
        ticker_idx = torch.tensor([ticker_idx_val], dtype=torch.long)

        # Compute features
        features = self._compute_features(ohlcv_rows)
        if features is None:
            return None

        # Run inference
        with torch.no_grad():
            features = features.to(self.device)
            ticker_idx = ticker_idx.to(self.device)
            logits = self.model(features, ticker_idx)
            probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]

        # Parse results
        pred_class = int(np.argmax(probs))
        confidence = float(probs[pred_class])
        probabilities = {
            CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))
        }

        return {
            "ticker": ticker.upper(),
            "direction": CLASS_NAMES[pred_class],
            "confidence": confidence,
            "probabilities": probabilities,
            "model_version": self.model_version,
        }


# Singleton instance - created at module level, loaded in lifespan
prediction_service = PredictionService()
```

**Why:** Singleton service loaded at startup via lifespan. Falls back gracefully when no champion model exists. Feature computation reuses ml/features.py for consistency with training. UNK embedding for unseen tickers.

---

#### Step 5.3 - Prediction Router

**File:** backend/src/prediction/router.py
**Action:** FastAPI router with GET /predict/{ticker}, Redis 6h cache, error handling.

```python
"""
FastAPI router for LSTM prediction endpoint.

Endpoints:
    - GET /predict/{ticker} - Directional forecast with Redis 6h cache
"""

from __future__ import annotations

import json
import structlog
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.cache.redis import get_redis
from src.config import settings
from src.limiter import limiter
from src.market.repository import get_ohlcv
from src.prediction.schemas import PredictionResponse
from src.prediction.service import prediction_service

logger = structlog.get_logger()

router = APIRouter()

PREDICTION_CACHE_TTL = 21600  # 6 hours


@router.get("/predict/{ticker}", response_model=PredictionResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def predict(
    request: Request,
    ticker: str,
    current_user: UserInDB = Depends(get_current_user),
) -> PredictionResponse:
    """Return directional forecast for a ticker.

    Uses the champion GlobalLSTM model loaded at startup.
    Results are cached in Redis for 6 hours (per ticker).

    Requires authentication (any authenticated user can fetch predictions).
    """
    ticker = ticker.upper()

    # Check Redis cache first
    cache_key = f"predict:{ticker}"
    try:
        r = await get_redis()
        if r is not None:
            cached = await r.get(cache_key)
            if cached is not None:
                try:
                    data = json.loads(cached)
                    return PredictionResponse(**data, cached=True)
                except (json.JSONDecodeError, TypeError):
                    pass  # Corrupted cache - recompute
    except Exception:
        logger.warning("redis_cache_read_failed", ticker=ticker)

    # Check model loaded
    if not prediction_service.is_loaded():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prediction model not yet loaded. Train and deploy a champion model first.",
        )

    # Fetch OHLCV data (90+ days for feature computation)
    rows = await get_ohlcv(ticker, limit=500)
    if not rows or len(rows) < 60:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Insufficient price data for {ticker}. Need at least 60 trading days.",
        )

    # Run prediction
    try:
        result = prediction_service.predict(ticker, rows)
    except Exception as exc:
        logger.exception("prediction_failed", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed for {ticker}",
        )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not compute prediction for {ticker}",
        )

    response = PredictionResponse(
        ticker=result["ticker"],
        direction=result["direction"],
        confidence=result["confidence"],
        probabilities=result["probabilities"],
        model_version=result["model_version"],
        cached=False,
        predicted_at=datetime.now(timezone.utc),
    )

    # Cache in Redis (graceful degradation on Redis failure)
    try:
        if r is not None:
            await r.setex(
                cache_key,
                PREDICTION_CACHE_TTL,
                response.model_dump_json(exclude={"cached"}),
            )
    except Exception:
        logger.warning("redis_cache_write_failed", ticker=ticker)

    return response
```

**Why:** Same pattern as market router. Redis cache with graceful degradation. Clear error messages for each failure mode. Model-not-loaded returns 503 (service unavailable, not 500).

---

#### Step 5.4 - Add Prediction Settings to config.py

**File:** backend/src/config.py
**Action:** Add prediction-related settings to the Settings class.

```python
# Add to Settings class:
    # Prediction
    PREDICTION_MODEL_PATH: str = "/model_artifacts/champion/model.pt"
    PREDICTION_CACHE_TTL: int = 21600
```

**Edit:**

```python
# After ENABLE_TWR: bool = True (line ~44)
    # Prediction
    PREDICTION_MODEL_PATH: str = "/model_artifacts/champion/model.pt"
    PREDICTION_CACHE_TTL: int = 21600
```

---

#### Step 5.5 - Register Prediction Router and Model Loading in main.py

**File:** backend/src/main.py
**Action:** Add prediction router import and registration. Add model loading to lifespan.

**Edit (lifespan function):**

```python
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("app_starting", environment=settings.ENVIRONMENT)
    # ... existing migrations and pool init ...

    # Seed categories on first startup
    from src.categories.seed import seed_categories
    seeded = await seed_categories()
    if seeded:
        logger.info("categories_seeded", count=seeded)

    # Load prediction model
    from src.prediction.service import prediction_service
    loaded = prediction_service.load_model(settings.PREDICTION_MODEL_PATH)
    if loaded:
        logger.info("prediction_model_loaded", path=settings.PREDICTION_MODEL_PATH)
    else:
        logger.warning("prediction_model_not_found", path=settings.PREDICTION_MODEL_PATH)

    yield
    # ... existing shutdown logic ...
```

**Edit (router registrations):**

```python
# Add after performance router import (~line 114):
from src.prediction.router import router as prediction_router  # noqa: E402

# Add after app.include_router(performance_router, ...):
app.include_router(prediction_router, prefix="/predict", tags=["prediction"])
```

---

#### Step 5.6 - Add Shared Volume to Backend Container

**File:** docker-compose.yml
**Action:** Mount the model_artifacts volume in the backend service.

```yaml
backend:
  # ... existing config ...
  volumes:
    - ./backend/src:/app/src
    - model_artifacts:/model_artifacts # NEW: read champion model
```

**Why:** The backend reads the champion model from the shared volume. This volume is written by the ML container during training.

---

#### Step 5.7 - Prediction Endpoint Tests

**File:** backend/tests/test_prediction.py
**Action:** ~20 tests for the prediction endpoint with mocked model and yfinance.

```python
"""Tests for the prediction endpoint."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_predict_no_model(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """When no model is loaded, return 503."""
    with patch("src.prediction.router.prediction_service.is_loaded", return_value=False):
        response = await client.get(
            "/predict/AAPL",
            headers=auth_headers,
        )
    assert response.status_code == 503
    assert "model not yet loaded" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_predict_no_data(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """When no OHLCV data exists, return 404."""
    with patch("src.prediction.router.prediction_service.is_loaded", return_value=True), \
         patch("src.prediction.router.get_ohlcv", return_value=[]):
        response = await client.get(
            "/predict/AAPL",
            headers=auth_headers,
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_predict_success(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Happy path: model loaded, data exists, returns prediction."""
    # Seed some OHLCV data
    from src.market.repository import upsert_ohlcv

    rows = []
    for i in range(100):
        d = date.today() - timedelta(days=100 - i)
        rows.append({
            "date": d.isoformat(),
            "open": 150.0 + i * 0.1,
            "high": 152.0 + i * 0.1,
            "low": 149.0 + i * 0.1,
            "close": 151.0 + i * 0.1,
            "adjusted_close": 150.0 + i * 0.1,
            "volume": 1000000,
        })
    await upsert_ohlcv("AAPL", rows)

    mock_result = {
        "ticker": "AAPL",
        "direction": "UP",
        "confidence": 0.75,
        "probabilities": {"DOWN": 0.1, "FLAT": 0.15, "UP": 0.75},
        "model_version": "1",
    }

    with patch("src.prediction.router.prediction_service.is_loaded", return_value=True), \
         patch("src.prediction.router.prediction_service.predict", return_value=mock_result), \
         patch("src.prediction.router.get_redis", return_value=None):
        response = await client.get(
            "/predict/AAPL",
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["direction"] == "UP"
    assert data["confidence"] == 0.75
    assert data["cached"] is False
    assert data["model_version"] == "1"


@pytest.mark.asyncio
async def test_predict_cache_hit(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """When Redis cache is fresh, return cached prediction."""
    import json

    mock_redis = AsyncMock()
    cached_data = json.dumps({
        "ticker": "AAPL", "direction": "DOWN", "confidence": 0.6,
        "probabilities": {"DOWN": 0.6, "FLAT": 0.3, "UP": 0.1},
        "model_version": "1", "predicted_at": "2026-07-01T12:00:00+00:00",
    })
    mock_redis.get.return_value = cached_data

    with patch("src.prediction.router.get_redis", return_value=mock_redis):
        response = await client.get(
            "/predict/AAPL",
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "DOWN"
    assert data["cached"] is True


@pytest.mark.asyncio
async def test_predict_requires_auth(client: AsyncClient) -> None:
    """Unauthenticated requests should return 401."""
    response = await client.get("/predict/AAPL")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_predict_invalid_ticker(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Non-existent ticker returns 404."""
    with patch("src.prediction.router.prediction_service.is_loaded", return_value=True), \
         patch("src.prediction.router.get_ohlcv", return_value=[]):
        response = await client.get(
            "/predict/INVALID123",
            headers=auth_headers,
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_predict_model_exception(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """If model.predict raises, return 500."""
    # Seed minimal data
    from src.market.repository import upsert_ohlcv
    await upsert_ohlcv("AAPL", [{
        "date": date.today().isoformat(),
        "adjusted_close": 150.0, "volume": 1000000,
    }])

    with patch("src.prediction.router.prediction_service.is_loaded", return_value=True), \
         patch("src.prediction.router.prediction_service.predict",
               side_effect=RuntimeError("OOM")), \
         patch("src.prediction.router.get_redis", return_value=None):
        response = await client.get(
            "/predict/AAPL",
            headers=auth_headers,
        )
    assert response.status_code == 500
```

Target: 15-20 tests total covering all cache states, error codes, model states, and edge cases.

---

### Round 6 - Full Training Execution

**Goal:** Fetch and cache 5 years of OHLCV for training tickers, run the full training pipeline, verify champion model registered.

**Files to create:** 0 (uses existing infrastructure)
**Files to modify:** 0

---

#### Step 6.1 - Pre-populate OHLCV Data for Training Tickers

**Action:** Run the existing market data endpoint to populate ohlcv_prices for all 55 training tickers.

**Steps:**

```bash
# For each training ticker, call the OHLCV endpoint to trigger data fetch
TICKERS="AAPL MSFT GOOGL AMZN NVDA META TSLA JPM V UNH XOM JNJ WMT PG MA CVX HD MRK ABBV KO PEP AVGO COST CRM BAC TMO MCD ABT ACN DIS DHR LIN NFLX CSCO ADBE NEE CMCSA PFE TXN BMY AMGN PM QCOM RTX IBM HON CAT INTU AMAT AMT MS PLD SBUX VZ GE"
for ticker in $TICKERS; do
  curl -s -H "Authorization: $(cat /tmp/test_token)" \
    "http://localhost:8000/market/ohlcv/$ticker?start_date=2021-01-01" > /dev/null
  echo "Fetched $ticker"
done
```

**Why:** The market endpoint fetches from yfinance and caches to PostgreSQL. After this step, all training data is in the ohlcv_prices table.

**Verify:** `docker compose run ml python -c "
import asyncpg
import asyncio
async def check():
    conn = await asyncpg.connect('postgresql://stocklens:stocklens@postgres:5432/stocklens')
    row = await conn.fetchval('SELECT COUNT(DISTINCT ticker) FROM ohlcv_prices')
    print(f'Tickers with data: {row}')
    await conn.close()
asyncio.run(check())
"` shows 50+ tickers.

---

#### Step 6.2 - Run the Training Pipeline

**Action:** Execute the full training pipeline.

```bash
docker compose run --rm ml python -m ml.pipeline
```

**Expected output:**

```
2026-07-02 10:00:00 [INFO] ml.pipeline: Starting ML pipeline
2026-07-02 10:00:05 [INFO] ml.pipeline: Fetched OHLCV data, tickers=52
2026-07-02 10:00:10 [INFO] ml.pipeline: Ticker vocabulary built, vocab_size=53, tickers=52
2026-07-02 10:00:15 [INFO] ml.pipeline: Global dataset prepared, samples=63000
2026-07-02 10:00:15 [INFO] ml.pipeline: Dataset split - train: 44100, val: 9450, test: 9450
2026-07-02 10:00:16 [INFO] ml.pipeline: Model initialised, params=142831
...
2026-07-02 10:15:00 [INFO] ml.evaluate: Test metrics:
    accuracy: 0.42
    directional_accuracy: 0.48
    simulated_sharpe: 1.2
    per_class_f1: {DOWN: 0.35, FLAT: 0.50, UP: 0.38}
```

**Expected metrics (baseline for a 3-class financial model):**

- Directional accuracy: 45-55% (random = 33%, any signal > random)
- Simulated Sharpe: 0.5-1.5 (positive is good)
- Per-class F1: should be >0.3 for all classes

---

#### Step 6.3 - Verify Champion Model Registration

**Action:** Check that the champion model is registered in MLflow and recorded in the DB.

```bash
# Check MLflow UI
open http://localhost:5000

# Check model_registry DB
docker compose run --rm ml python -c "
import asyncpg, asyncio, json
async def check():
    conn = await asyncpg.connect('postgresql://stocklens:stocklens@postgres:5432/stocklens')
    row = await conn.fetchrow(
        \"SELECT * FROM model_registry WHERE alias = 'champion'\"
    )
    if row:
        print(f'Champion model: run_id={row[\"mlflow_run_id\"]}, version={row[\"model_version\"]}')
        metrics = json.loads(row['metrics'])
        print(f'Metrics: {json.dumps(metrics, indent=2)}')
    else:
        print('No champion model found')
    await conn.close()
asyncio.run(check())
"

# Check champion model on disk
ls -la /model_artifacts/champion/model.pt
```

**Verify:**

- MLflow UI shows the run with params, metrics, artifacts (loss curves, confusion matrix)
- model_registry has a row with alias='champion'
- /model_artifacts/champion/model.pt exists

---

### Round 7 - Frontend Integration

**Goal:** Frontend prediction service, LSTM projections replacing hardcoded CAGR, PredictionCard component.

**Files to create:** 2 (frontend/src/services/prediction.ts, frontend/src/components/PredictionCard.tsx)
**Files to modify:** 4 (frontend/src/services/projectionService.ts, frontend/src/services/market.ts, frontend/src/screens/SummaryScreen.tsx, frontend/src/screens/ReceiptDetailsScreen.tsx)

---

#### Step 7.1 - Create Frontend Prediction Service

**File:** frontend/src/services/prediction.ts
**Action:** Typed service wrapper for the prediction endpoint.

```typescript
/**
 * Prediction service - LSTM directional forecasts from backend.
 */

import { apiService } from './api';

export interface PredictionResponse {
  ticker: string;
  direction: 'UP' | 'FLAT' | 'DOWN';
  confidence: number;
  probabilities: {
    DOWN: number;
    FLAT: number;
    UP: number;
  };
  model_version: string;
  cached: boolean;
  predicted_at: string;
}

export const predictionService = {
  async getPrediction(ticker: string): Promise<PredictionResponse> {
    return apiService.get<PredictionResponse>(`/predict/${ticker}`);
  },
};
```

**Why:** Single endpoint wrapper. Returns typed PredictionResponse for use in screens.

---

#### Step 7.2 - Update Market Service Types

**File:** frontend/src/services/market.ts
**Action:** Add import/re-export of PredictionResponse type.

```typescript
// Add at top of file after existing types
export type { PredictionResponse } from './prediction';
```

**Why:** Allows screens to import PredictionResponse from either service.

---

#### Step 7.3 - Update Projection Service

**File:** frontend/src/services/projectionService.ts
**Action:** Add getLSTMPrediction() function that uses LSTM as primary source, falls back to CAGR.

```typescript
// Add after existing functions:

import { predictionService, PredictionResponse } from './prediction';

/**
 * Get LSTM-based directional prediction for a ticker.
 *
 * @param ticker - Stock ticker symbol
 * @returns PredictionResponse or null if unavailable
 */
export async function getLSTMPrediction(ticker: string): Promise<PredictionResponse | null> {
  try {
    return await predictionService.getPrediction(ticker);
  } catch {
    return null;
  }
}

/**
 * Get combined projection: LSTM direction + CAGR rate.
 * Uses LSTM as primary signal, CAGR as fallback growth rate.
 *
 * @param ticker - Stock ticker symbol
 * @returns Object with direction, rate, confidence, or null
 */
export async function getCombinedProjection(ticker: string): Promise<{
  direction: 'UP' | 'FLAT' | 'DOWN';
  rate: number;
  confidence: number;
  model_version: string;
} | null> {
  try {
    const prediction = await predictionService.getPrediction(ticker);
    // Use LSTM prediction direction, fall back CAGR for rate
    const cagr = await getCAGR(ticker);
    return {
      direction: prediction.direction,
      rate: cagr ?? 0.1,
      confidence: prediction.confidence,
      model_version: prediction.model_version,
    };
  } catch {
    // Fall back to CAGR-only
    const cagr = await getCAGR(ticker);
    if (cagr === null) return null;
    return {
      direction: cagr > 0 ? 'UP' : 'DOWN',
      rate: cagr,
      confidence: 0.5,
      model_version: 'cagr-fallback',
    };
  }
}
```

---

#### Step 7.4 - Create PredictionCard Component

**File:** frontend/src/components/PredictionCard.tsx
**Action:** Card showing LSTM prediction direction, confidence bar, and probabilities.

```tsx
/**
 * PredictionCard - displays LSTM directional forecast.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';

interface PredictionCardProps {
  ticker: string;
  direction: 'UP' | 'FLAT' | 'DOWN';
  confidence: number;
  probabilities: {
    DOWN: number;
    FLAT: number;
    UP: number;
  };
  modelVersion: string;
  compact?: boolean;
}

const DIRECTION_COLORS: Record<string, string> = {
  UP: brandColors.green,
  FLAT: brandColors.yellow ?? '#FFA500',
  DOWN: brandColors.red,
};

const DIRECTION_ICONS: Record<string, string> = {
  UP: '\u25B2', // ▲
  FLAT: '\u25B6', // ▶
  DOWN: '\u25BC', // ▼
};

export default function PredictionCard({
  ticker,
  direction,
  confidence,
  probabilities,
  modelVersion,
  compact = false,
}: PredictionCardProps) {
  const { theme } = useTheme();
  const dirColor = DIRECTION_COLORS[direction];
  const icon = DIRECTION_ICONS[direction];

  if (compact) {
    return (
      <View style={[styles.compactContainer, { backgroundColor: theme.surface }]}>
        <Text style={[styles.compactIcon, { color: dirColor }]}>{icon}</Text>
        <Text style={[styles.compactDirection, { color: dirColor }]}>{direction}</Text>
        <Text style={[styles.compactConfidence, { color: theme.textSecondary }]}>
          {(confidence * 100).toFixed(0)}%
        </Text>
      </View>
    );
  }

  const probBars = [
    { label: 'DOWN', value: probabilities.DOWN, color: brandColors.red },
    { label: 'FLAT', value: probabilities.FLAT, color: '#FFA500' },
    { label: 'UP', value: probabilities.UP, color: brandColors.green },
  ];

  return (
    <View style={[styles.container, { backgroundColor: theme.surface }]}>
      <View style={styles.header}>
        <Text style={[styles.ticker, { color: theme.text }]}>{ticker}</Text>
        <Text style={[styles.modelVersion, { color: theme.textSecondary }]}>v{modelVersion}</Text>
      </View>

      <View style={styles.predictionRow}>
        <Text style={[styles.icon, { color: dirColor }]}>{icon}</Text>
        <Text style={[styles.direction, { color: dirColor }]}>{direction}</Text>
        <Text style={[styles.confidence, { color: theme.textSecondary }]}>
          {(confidence * 100).toFixed(1)}% confidence
        </Text>
      </View>

      <View style={styles.probabilityBars}>
        {probBars.map(({ label, value, color }) => (
          <View key={label} style={styles.probRow}>
            <Text style={[styles.probLabel, { color: theme.textSecondary }]}>{label}</Text>
            <View style={[styles.barBg, { backgroundColor: theme.background }]}>
              <View
                style={[
                  styles.barFill,
                  { width: `${(value * 100).toFixed(0)}%`, backgroundColor: color },
                ]}
              />
            </View>
            <Text style={[styles.probValue, { color: theme.text }]}>
              {(value * 100).toFixed(0)}%
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radii.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  ticker: {
    ...typography.sectionTitle,
  },
  modelVersion: {
    ...typography.caption,
  },
  predictionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  icon: {
    fontSize: 24,
    marginRight: spacing.sm,
  },
  direction: {
    ...typography.metric,
    marginRight: spacing.md,
  },
  confidence: {
    ...typography.body,
  },
  probabilityBars: {
    gap: spacing.sm,
  },
  probRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  probLabel: {
    width: 50,
    ...typography.caption,
  },
  barBg: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    marginHorizontal: spacing.sm,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 4,
  },
  probValue: {
    width: 35,
    textAlign: 'right',
    ...typography.captionStrong,
  },
  compactContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radii.md,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    gap: spacing.xs,
  },
  compactIcon: {
    fontSize: 12,
  },
  compactDirection: {
    ...typography.captionStrong,
  },
  compactConfidence: {
    ...typography.caption,
  },
});
```

---

#### Step 7.5 - Update SummaryScreen Projection

**File:** frontend/src/screens/SummaryScreen.tsx
**Action:** Replace hardcoded 10% projection with LSTM-based prediction average.

**Edit (the projection StatCard, around line 382-395):**

Replace:

```tsx
<StatCard
  value={
    <IconValue
      iconName="trending-up"
      iconSize={28}
      iconColor={theme.primary}
      value={formatCurrency(totalMoneySpent * Math.pow(1.1, 20))}
      valueStyle={[styles.projectionValue, { color: theme.text }]}
    />
  }
  label="20-Year Portfolio Projection"
  subtitle={`If your total spending of ${formatCurrency(totalMoneySpent)} grew at 10% per year`}
  variant="white"
  style={{ width: '100%', marginBottom: spacing.md, marginHorizontal: 0 }}
/>
```

With a dynamic version that fetches LSTM predictions for top tickers:

```tsx
// Add at top with other imports:
import { getCombinedProjection } from '../services/projectionService';
import { STOCK_PRESETS } from '../services/stockPresets';

// Add state inside SummaryScreen component:
const [lstmRate, setLstmRate] = useState<number>(0.1); // Fallback 10%
const [lstmDirection, setLstmDirection] = useState<string>('UP');
const [lstmLoaded, setLstmLoaded] = useState(false);

// Add effect alongside the existing useEffect:
useEffect(() => {
  let mounted = true;
  async function loadLstmProjection() {
    try {
      // Average predictions across preset tickers
      let totalRate = 0;
      let count = 0;
      for (const stock of STOCK_PRESETS.slice(0, 5)) {
        const proj = await getCombinedProjection(stock.ticker);
        if (proj) {
          totalRate += proj.rate;
          count++;
        }
      }
      if (!mounted) return;
      if (count > 0) {
        setLstmRate(totalRate / count);
        setLstmDirection('UP');
        setLstmLoaded(true);
      }
    } catch {
      // Keep default fallback
    }
  }
  loadLstmProjection();
  return () => {
    mounted = false;
  };
}, []);
```

Then replace the StatCard projection value:

```tsx
<StatCard
  value={
    <IconValue
      iconName="trending-up"
      iconSize={28}
      iconColor={theme.primary}
      value={formatCurrency(totalMoneySpent * Math.pow(1 + lstmRate, 20))}
      valueStyle={[styles.projectionValue, { color: theme.text }]}
    />
  }
  label="20-Year Portfolio Projection"
  subtitle={
    lstmLoaded
      ? `LSTM-forecasted: ${(lstmRate * 100).toFixed(1)}% avg annual return`
      : `If your total spending of ${formatCurrency(totalMoneySpent)} grew at 10% per year`
  }
  variant="white"
  style={{ width: '100%', marginBottom: spacing.md, marginHorizontal: 0 }}
/>
```

---

#### Step 7.6 - Update ReceiptDetailsScreen with Predictions

**File:** frontend/src/screens/ReceiptDetailsScreen.tsx
**Action:** Add prediction badge/chip to each StockCard showing LSTM direction.

**Edit (inside renderStockCard, add a prediction badge):**

Add import at top:

```typescript
import { getLSTMPrediction, PredictionResponse } from '../services/projectionService';
```

Add state for predictions:

```typescript
const [predictions, setPredictions] = useState<Record<string, PredictionResponse | null>>({});
const [predictionsLoading, setPredictionsLoading] = useState(true);
```

Add effect to load predictions:

```typescript
useEffect(() => {
  let mounted = true;
  async function loadPredictions() {
    setPredictionsLoading(true);
    const results: Record<string, PredictionResponse | null> = {};
    for (const stock of STOCK_PRESETS) {
      try {
        const pred = await getLSTMPrediction(stock.ticker);
        results[stock.ticker] = pred;
      } catch {
        results[stock.ticker] = null;
      }
    }
    if (mounted) {
      setPredictions(results);
      setPredictionsLoading(false);
    }
  }
  loadPredictions();
  return () => {
    mounted = false;
  };
}, []);
```

Then add the PredictionCard (compact) inside StockCard, just after the ticker display:

```tsx
{
  predictions[investmentValue.ticker] && (
    <PredictionCard
      ticker={investmentValue.ticker}
      direction={predictions[investmentValue.ticker]!.direction}
      confidence={predictions[investmentValue.ticker]!.confidence}
      probabilities={predictions[investmentValue.ticker]!.probabilities}
      modelVersion={predictions[investmentValue.ticker]!.model_version}
      compact
    />
  );
}
```

Update the warning text at the bottom:

```tsx
<Text style={[styles.warningText, { color: theme.text }]}>
  Projections are hypothetical.{' '}
  {lstmLoaded
    ? 'LSTM model predictions shown with confidence scores.'
    : 'Projections based on historical CAGR.'}{' '}
  Past performance does not guarantee future results.
</Text>
```

**Note:** Per-ticker directional accuracy is not tracked in V1 (the global model has a single validation accuracy, not per-ticker). The confidence score from each prediction serves as the quality indicator. A future phase can add per-ticker accuracy tracking and display it here.

---

## Testing Strategy

### Test Modules

| Test File                      | Count   | DB Required? | Description                             |
| ------------------------------ | ------- | ------------ | --------------------------------------- |
| tests/test_ml/test_features.py | ~15     | No           | Technical indicator computation         |
| tests/test_ml/test_labeling.py | ~10     | No           | Adaptive label computation              |
| tests/test_ml/test_dataset.py  | ~10     | No           | SequenceDataset, sliding windows, split |
| tests/test_ml/test_model.py    | ~10     | No           | GlobalLSTM forward pass, save/load      |
| tests/test_ml/test_evaluate.py | ~15     | No           | Metrics, F1, confusion matrix, Sharpe   |
| tests/test_prediction.py       | ~20     | Yes          | Prediction endpoint (uses conftest)     |
| **Total**                      | **~80** |              |                                         |

### Key Testing Patterns

1. **ML unit tests** (test_ml/): Pure numpy/torch functions, no DB access needed. Run inside the pytest container but don't require it.

2. **Prediction endpoint tests** (test_prediction.py): Use existing conftest.py with `_test_db` transaction rollback, `client`, `auth_headers`. Mock `prediction_service.predict()` to avoid loading the actual model.

3. **Mock strategy for prediction tests:**
   - `prediction_service.is_loaded` -> control whether model is loaded
   - `prediction_service.predict` -> return mock results
   - `get_redis` -> mock for cache tests
   - `get_ohlcv` -> seed DB for data availability

---

## Success Criteria

- [ ] ML Docker image builds and `docker compose build ml` succeeds
- [ ] MLflow tracking server starts and is accessible at http://localhost:5000
- [ ] All feature functions pass unit tests (test_features.py)
- [ ] All labeling functions pass unit tests (test_labeling.py)
- [ ] All dataset functions pass unit tests (test_dataset.py)
- [ ] All model functions pass unit tests (test_model.py)
- [ ] All evaluation functions pass unit tests (test_evaluate.py)
- [ ] Full training pipeline runs to completion: `docker compose run ml python -m ml.pipeline`
- [ ] Champion model registered in MLflow with params, metrics, loss curves, confusion matrix
- [ ] Champion model saved to /model_artifacts/champion/model.pt
- [ ] Champion model recorded in model_registry DB table with alias='champion'
- [ ] Backend starts with prediction model loaded (logs: "prediction_model_loaded")
- [ ] GET /predict/{ticker} returns PredictionResponse for tickers with data
- [ ] GET /predict/{ticker} returns 503 when no model loaded
- [ ] GET /predict/{ticker} returns 404 for unknown tickers
- [ ] GET /predict/{ticker} returns cached response within 6h (Redis hit)
- [ ] All 80+ ML tests pass (test_ml/\* + test_prediction.py)
- [ ] All existing Phase 1 + Phase 2 tests still pass (240+ tests)
- [ ] PredictionCard component renders correctly (direction, confidence, probabilities)
- [ ] SummaryScreen shows LSTM-based projection instead of hardcoded 10%
- [ ] ReceiptDetailsScreen shows prediction badges on StockCards
- [ ] `ruff check src/ tests/` zero errors
- [ ] `npx tsc --noEmit` zero errors (frontend)

---

## Risks & Mitigations

| Risk                                                          | Impact | Mitigation                                                                                                                       |
| ------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Not enough OHLCV data for 55 tickers (some have <5yr history) | Medium | Pipeline logs warnings and skips tickers with <60 days. 50+ tickers with 5yr data should yield ~63K sequences                    |
| Class imbalance (FLAT class dominates)                        | Medium | Weighted cross-entropy handles this. Monitor per-class F1 and retune threshold_mult if needed                                    |
| Training is slow on CPU (~15 min)                             | Low    | Expected for 63K samples x 100 epochs. MPS on Apple Silicon provides ~2x speedup. Acceptable for re-training schedule            |
| MLflow SQLite DB corruption                                   | Medium | SQLite backend is adequate for single-user dev. For production, switch to PostgreSQL backend                                     |
| Model overfits to training tickers                            | Medium | Early stopping (patience 10) + dropout (0.3) mitigate overfitting. Monitor val/test gap                                          |
| Redis prediction cache returns stale predictions              | Low    | 6h TTL is appropriate for next-day directional forecasts. For same-day updates, frontend can force-refresh (omit cache)          |
| Backend torch dependency adds image size                      | Low    | CPU-only torch adds ~200MB. Total backend image ~1.0GB. Acceptable for now                                                       |
| Model artifact path mismatch                                  | Medium | ML and backend containers share model_artifacts volume. Pipeline writes to same path backend reads from. Verified in integration |

---

## Verification Checklist

- [ ] `docker compose build ml` - builds ML training image
- [ ] `docker compose up -d mlflow` - starts MLflow tracking server
- [ ] `docker compose run --rm ml python -c "from ml.features import compute_all_features; print('OK')"` - ML module importable
- [ ] `docker compose run --rm backend python -c "from src.prediction.service import prediction_service; print('OK')"` - Prediction service importable
- [ ] `docker compose run --rm backend python -c "import torch; print(torch.__version__)"` - torch installed in backend
- [ ] `docker compose run --rm ml python -m pytest tests/test_ml/ -v` - ML tests pass
- [ ] `docker compose run --rm pytest python -m pytest tests/test_prediction.py tests/test_ml/ -v --cov=src --cov=ml` - All ML+prediction tests pass
- [ ] `ruff check src/ tests/` - zero lint errors
- [ ] MLflow UI shows completed run with metrics, params, artifacts
- [ ] `model_registry` DB has champion record
- [ ] `/model_artifacts/champion/model.pt` exists
- [ ] Backend logs "prediction_model_loaded" on startup
- [ ] `GET /predict/AAPL` returns 200 with valid prediction
- [ ] `GET /predict/INVALID` returns 404
- [ ] `npx tsc --noEmit` zero errors
- [ ] Jest tests pass (existing + new): `npx jest --passWithNoTests`
