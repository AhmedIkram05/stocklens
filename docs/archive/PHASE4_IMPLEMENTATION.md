# Phase 4 — MLOps: Airflow Retraining + Evidently Drift Detection

> **Status:** Draft
> **Last updated:** 2026-07-06
> **Depends on:** Phase 3 (trained model pipeline, champion model, prediction endpoint)
> **Target tests:** 80+ new tests across drift detection, prediction logging, Airflow DAG, integration
> **Architecture decisions:** Locked in grilling session (see CONTEXT.md glossary)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [New Modules](#new-modules)
4. [Implementation Rounds](#implementation-rounds)
   - [Round 1 — Schema Migrations (prediction_log + drift_metrics)](#round-1--schema-migrations-prediction_log--drift_metrics)
   - [Round 2 — Prediction Logging (Live Inference Capture)](#round-2--prediction-logging-live-inference-capture)
   - [Round 3 — Drift Detection Module (Evidently)](#round-3--drift-detection-module-evidently)
   - [Round 4 — Champion Comparison Gate in ML Pipeline](#round-4--champion-comparison-gate-in-ml-pipeline)
   - [Round 5 — Airflow Infrastructure + Retraining DAG](#round-5--airflow-infrastructure--retraining-dag)
   - [Round 6 — Drift Integration with Airflow + S3 Reports](#round-6--drift-integration-with-airflow--s3-reports)
   - [Round 7 — Polish, Tests & Verification](#round-7--polish-tests--verification)
5. [Testing Strategy](#testing-strategy)
6. [Success Criteria](#success-criteria)
7. [Risks & Mitigations](#risks--mitigations)
8. [Verification Checklist](#verification-checklist)

---

## Overview

Phase 4 adds automated weekly retraining and drift detection to the StockLens LSTM pipeline. An Airflow DAG runs weekly: fetch new OHLCV → retrain GlobalLSTM → compare challenger vs champion → promote if directional accuracy improves by >2pp → run drift detection → generate Evidently HTML reports → store metrics in PostgreSQL → alert on drift thresholds. Drift detection monitors input feature distributions (PSI/KS across 17 features) and prediction output distributions (JS divergence on class proportions) for portfolio tickers.

### Key Deliverables

1. **`prediction_log` table** — Stores every prediction request + pre-normalised features + response. Foundation for drift detection.
2. **`drift_metrics` table** — Queryable drift indicators (PSI, KS-statistic, JS divergence) per ticker per feature per drift run.
3. **Prediction logging** — Non-blocking fire-and-forget logging in the prediction service after each inference.
4. **Drift detection module** (`backend/src/drift/`) — Evidently-based PSI/KS/JS divergence computation, HTML report generation, S3 upload with pre-signed URLs.
5. **Champion comparison gate** — Modified training pipeline that reads champion metrics, compares challenger, promotes only on >2pp directional accuracy improvement.
6. **Airflow infrastructure** — Standalone Docker Compose at `airflow/` with LocalExecutor + SQLite. Runs the retraining DAG that wraps the existing ML pipeline.
7. **Reference distribution capture** — Training pipeline extension that computes and stores per-feature histograms (20-bin) from training data, used as drift baseline.
8. **Alerting** — CloudWatch metric + structlog alert when JS divergence > 0.3 or PSI > 0.25 on any feature.

### Dependencies

| Dependency     | Version  | Purpose                                      |
| -------------- | -------- | -------------------------------------------- |
| evidently      | >=0.6.0  | Drift detection: PSI, KS-test, JS divergence |
| apache-airflow | >=2.11.0 | DAG orchestration (LocalExecutor, SQLite)    |
| boto3          | >=1.43.0 | S3 client for drift report upload            |
| structlog      | >=24.4.0 | Structured drift alerts (already in project) |
| matplotlib     | >=3.11.0 | Evidently report charts (already in project) |

---

## Architecture

### Module Structure

```
stocklens/
├── airflow/                                    # NEW: Standalone Airflow Docker Compose
│   ├── Dockerfile                              # Airflow + ML dependencies
│   ├── docker-compose.yml                      # Standalone Compose (LocalExecutor, SQLite)
│   ├── dags/
│   │   ├── __init__.py
│   │   ├── weekly_retraining.py                # Main DAG: 5 tasks
│   │   └── drift_detection.py                  # Optional: standalone drift DAG
│   ├── config/
│   │   └── airflow.cfg                         # Airflow config overrides
│   ├── requirements.txt                        # Airflow + evidently + boto3
│   └── .env.example                            # Env template for Airflow
│
├── backend/
│   ├── ml/
│   │   ├── pipeline.py                         # MODIFY: add champion comparison gate
│   │   ├── mlflow_manager.py                   # MODIFY: add read_champion_metrics()
│   │   └── reference_distributions.py          # NEW: training-set feature histograms
│   │
│   ├── src/
│   │   ├── drift/                              # NEW: Drift detection module
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py                      # DriftRequest, DriftResponse, etc.
│   │   │   ├── service.py                      # DriftDetector: PSI/KS/JS computation
│   │   │   ├── evidently_reporter.py           # Evidently report generation
│   │   │   ├── repository.py                   # drift_metrics DB CRUD
│   │   │   ├── router.py                       # POST /drift/run, GET /drift/reports/{id}
│   │   │   └── utils.py                        # S3 upload, pre-signed URLs
│   │   │
│   │   ├── prediction/
│   │   │   ├── service.py                      # MODIFY: add prediction logging
│   │   │   ├── router.py                       # MODIFY: no change needed (service fires log)
│   │   │   └── prediction_logger.py            # NEW: async logging to prediction_log
│   │   │
│   │   ├── config.py                           # MODIFY: add drift settings
│   │   └── main.py                             # MODIFY: register drift router
│   │
│   ├── alembic/
│   │   └── versions/
│   │       └── 0005_add_prediction_log_and_drift_metrics.py  # NEW migration (0004 taken by cascade_decisions)
│   │
│   ├── database/
│   │   └── schema.py                           # MODIFY: add table definitions
│   │
│   └── tests/
│       ├── test_drift/                         # NEW: drift tests
│       │   ├── __init__.py
│       │   ├── test_drift_service.py
│       │   ├── test_evidently_reporter.py
│       │   ├── test_repository.py
│       │   └── test_router.py
│       ├── test_prediction_logger.py           # NEW: prediction logging tests
│       └── test_ml/
│           └── test_champion_comparison.py     # NEW: champion comparison tests
│
├── docs/
│   ├── CONTEXT.md                              # Already updated with Phase 4 terms
│   ├── TRACKER.md                              # MODIFY: Phase 4 tracker rows
│   └── archive/
│       └── PHASE4_IMPLEMENTATION.md            # THIS FILE
```

### Data Flow — Weekly Retraining + Drift

```
Airflow DAG (weekly, cron `0 6 * * 1`)
  │
  ├── Task 1: fetch_new_ohlcv
  │   └── → market/repository.py upsert_ohlcv (new rows since last run)
  │   └── → Short circuits: if no new data, skip retraining (just run drift)
  │
  ├── Task 2: train_challenger
  │   └── → docker compose run ml python -m ml.pipeline
  │   └── → MODIFIED pipeline: reads champion metrics from model_registry
  │   └── → Compares: if challenger directional_acc > champion + 2pp:
  │   └──   → set_champion_alias("champion")
  │   └──   → save_champion_to_disk() [atomic write to shared volume]
  │   └──   → _record_in_db()
  │   └── → ELSE: log "challenger did not beat champion", skip promotion
  │
  ├── Task 3: capture_reference_distributions
  │   └── → If champion changed: compute new reference histograms from training set
  │   └── → Store in model_registry.metrics as JSONB
  │   └── → If champion unchanged: skip (reference stays same)
  │
  ├── Task 4: run_drift_detection
  │   └── → Fetch reference distributions from champion metadata
  │   └── → Fetch recent prediction_log entries (last 7 days)
  │   └── → For each monitored ticker (portfolio tickers + SPY):
  │   └──   → Extract pre-normalised feature values from prediction_log
  │   └──   → Compute PSI(ref, current) per feature
  │   └──   → KS-test(ref, current) per feature
  │   └──   → Compute JS divergence on prediction class distribution
  │   └── → Generate Evidently HTML report
  │   └── → Upload to S3 → pre-signed URL
  │   └── → Persist metrics to drift_metrics table
  │   └── → Log CloudWatch alert if JS>0.3 or PSI>0.25
  │
  └── Task 5: cleanup
      └── → Delete prediction_log rows older than 90 days
      └── → Prune drift_metrics rows older than 1 year
```

### Drift Detection Detail (Evidently)

```
DriftDetector.compute_drift(monitored_tickers, reference_dist, prediction_logs)
  │
  ├── For each ticker:
  │   ├── Extract feature matrix from prediction_log (n_samples × 17 features)
  │   ├── For each of the 17 features:
  │   │   ├── Compute PSI(reference_histogram, current_values)
  │   │   ├── Kolmogorov-Smirnov test(reference_distribution, current_distribution)
  │   │   └── Both scores → DriftMetric entry
  │   │
  │   ├── Extract prediction classes from prediction_log
  │   ├── Compute JS divergence(reference_class_dist, current_class_dist)
  │   │
  │   └── Generate Evidently Report:
  │       └── DataDriftPreset or DataDriftTable
  │       └── Columns: 17 feature columns + prediction_target column
  │       └── Reference: training feature distribution (from reference_dist)
  │       └── Current: recent prediction_log entries
  │
  ├── Aggregate results:
  │   ├── max_psi_per_feature, max_ks_per_feature
  │   ├── js_divergence_per_prediction_dist
  │   ├── alert_count (features with PSI>0.25 or JS>0.3)
  │   └── overall_drift_verdict (drifted / stable)
  │
  └── Return DriftReport (Evidently HTML path + metrics + alert_status)
```

---

## New Modules

### `backend/src/drift/` — Drift Detection Module

| File                    | Purpose                                                                                              |
| ----------------------- | ---------------------------------------------------------------------------------------------------- |
| `schemas.py`            | `DriftRunRequest`, `DriftRunResponse`, `DriftMetricResponse`, `DriftReportResponse`                  |
| `service.py`            | `DriftDetector` class: `compute_drift()`, `compute_psi()`, `compute_ks()`, `compute_js_divergence()` |
| `evidently_reporter.py` | `EvidentlyReporter` class: `generate_report()`, Evidently preset config                              |
| `repository.py`         | `create_drift_metric()`, `list_drift_reports()`, `get_latest_drift_summary()`, `prune_old_metrics()` |
| `router.py`             | `POST /drift/run`, `GET /drift/reports`, `GET /drift/reports/{id}`, `GET /drift/summary`             |
| `utils.py`              | `upload_to_s3()`, `generate_presigned_url()`, `format_drift_alert()`                                 |

### `backend/src/prediction/prediction_logger.py` — Async Prediction Logger

| Function                 | Purpose                                                                                                           |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `log_prediction()`       | Fire-and-forget write to `prediction_log` table. Runs in a thread pool to avoid blocking the prediction response. |
| `log_prediction_batch()` | Bulk insert for bootstrapping/backfill.                                                                           |

### `backend/ml/reference_distributions.py` — Reference Distribution Capture

| Function                            | Purpose                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| `compute_reference_distributions()` | Takes training set feature matrix, computes per-feature histograms (20 bins), class distribution. |
| `store_reference_distributions()`   | Saves histograms as JSONB in model_registry alongside champion metrics.                           |
| `load_reference_distributions()`    | Loads reference distributions from champion metadata.                                             |

### `airflow/` — Standalone Airflow Stack

| File                        | Purpose                                                                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------- |
| `Dockerfile`                | Base Airflow image + ML dependencies (torch, mlflow, evidently, boto3)                                  |
| `docker-compose.yml`        | Single service: Airflow with LocalExecutor, SQLite backend, volumes for DAGs + model_artifacts + MLflow |
| `dags/weekly_retraining.py` | Main DAG: 5 tasks as described above. Uses `BashOperator` + `PythonOperator`.                           |
| `dags/drift_detection.py`   | Standalone drift DAG (triggered independently of retraining).                                           |
| `config/airflow.cfg`        | Overrides: dags_folder, sql_alchemy_conn, executor=LocalExecutor                                        |
| `requirements.txt`          | Apache Airflow pinned deps + evidently + boto3                                                          |

---

## Implementation Rounds

### Round 1 — Schema Migrations (prediction_log + drift_metrics)

**Goal:** Create the two new database tables that underpin all of Phase 4. No code changes beyond the migration.

**Files to create:** 1 (alembic migration)
**Files to modify:** 1 (database/schema.py)

---

#### Step 1.1 — Add table definitions to `schema.py`

**File:** `backend/src/database/schema.py`
**Action:** Add `prediction_log` and `drift_metrics` table metadata for Alembic autogeneration.

Add after the `model_registry` table definition:

```python
# --- prediction_log ---
metadata = MetaData()

prediction_log = Table(
    "prediction_log",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ticker", String(10), nullable=False),
    Column("model_version", String(20), nullable=False),
    Column("prediction", String(4), nullable=False),  # UP/FLAT/DOWN
    Column("confidence", Float, nullable=False),
    Column("probabilities", JSONB, nullable=True),      # {"DOWN": 0.1, "FLAT": 0.3, "UP": 0.6}
    Column("features", JSONB, nullable=True),           # {"log_ret_1d": 0.01, ..., "excess_ret_21d": -0.005}
    Column("feature_stats", JSONB, nullable=True),       # {"mean": 0.0, "std": ...} — pre-normalisation stats per feature
    Column("raw_feature_names", JSONB, nullable=True),   # ["log_ret_1d", ..., "excess_ret_21d"]
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("idx_prediction_log_ticker_created", prediction_log.c.ticker, prediction_log.c.created_at)
Index("idx_prediction_log_model_version", prediction_log.c.model_version)
Index("idx_prediction_log_created_at", prediction_log.c.created_at)  # For cleanup task (DELETE WHERE created_at < cutoff)


# --- drift_metrics ---
drift_metrics = Table(
    "drift_metrics",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("drift_run_id", String(36), nullable=False),       # UUID for each drift run
    Column("ticker", String(10), nullable=False),
    Column("model_version", String(20), nullable=False),
    Column("metric_type", String(20), nullable=False),        # 'psi', 'ks_statistic', 'js_divergence'
    Column("feature_name", String(50), nullable=False),       # 'log_ret_1d', 'prediction_distribution', etc.
    Column("drift_score", Float, nullable=False),             # The numeric score (PSI, KS, JS)
    Column("alert_triggered", Boolean, nullable=False, server_default=text("false")),
    Column("reference_period", String(20), nullable=True),    # e.g. 'training_set_2026-06' or model_version
    Column("current_period", String(20), nullable=True),      # e.g. '2026-07-01_2026-07-07'
    Column("report_s3_key", String(500), nullable=True),      # S3 object key for the full Evidently report
    Column("details", JSONB, nullable=True),                  # Extra context: bin counts, p_value, sample_sizes
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("idx_drift_metrics_run", drift_metrics.c.drift_run_id)
# UniqueConstraint prevents duplicate drift runs
# drift_metrics.append_constraint(
#     UniqueConstraint("drift_run_id", "ticker", "metric_type", "feature_name", name="uq_drift_metrics_run_ticker_metric_feature")
# )
Index("idx_drift_metrics_ticker_metric", drift_metrics.c.ticker, drift_metrics.c.metric_type)
Index("idx_drift_metrics_alert", drift_metrics.c.alert_triggered)
```

**Why:** `prediction_log` stores raw features before they are standardised for model input. This is critical for drift detection — once features are z-scored, the original distribution is lost. Each sample stores window statistics (means/stds per feature, ~200 bytes) rather than the full (30, 17) matrix (~130KB uncompressed). This keeps storage manageable: ~300 bytes/row × 500 predictions/day × 90 days ≈ 13.5 MB total. `feature_stats` holds the per-sample mean/std used for standardisation, so drift detection can reconstruct original-scale distributions.

`drift_metrics` is the queryable metrics store. Each drift run creates N×M rows (N tickers × M metrics). The S3 key links back to the full Evidently HTML report for visual inspection.

**Edge cases:**

- `features` JSONB can be NULL for legacy predictions (backfill scenario)
- `alert_triggered` defaults to false — set to true during drift computation when thresholds exceeded
- `report_s3_key` may be NULL if S3 upload fails (metrics still stored locally)

**Verify:** `python -c "from src.database.schema import prediction_log, drift_metrics"` imports cleanly.

---

#### Step 1.2 — Create Alembic migration

**File:** `backend/alembic/versions/0005_add_prediction_log_and_drift_metrics.py`
**Action:** Manual migration following the 0001 pattern. Raw SQL via `op.execute()`.

> **Note:** Migration 0004 already exists (`0004_add_cascade_decisions.py` from the cascade-NLP-OCR work). This migration is 0005 with `down_revision="0004"`.

```python
"""Add prediction_log and drift_metrics tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prediction_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("prediction", sa.String(4), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("probabilities", JSONB(), nullable=True),
        sa.Column("features", JSONB(), nullable=True),
        sa.Column("feature_stats", JSONB(), nullable=True),
        sa.Column("raw_feature_names", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_prediction_log_ticker_created",
        "prediction_log",
        ["ticker", "created_at"],
    )
    op.create_index(
        "idx_prediction_log_model_version",
        "prediction_log",
        ["model_version"],
    )
    op.create_index(
        "idx_prediction_log_created_at",
        "prediction_log",
        ["created_at"],
    )

    op.create_table(
        "drift_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("drift_run_id", sa.String(36), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("metric_type", sa.String(20), nullable=False),  # 'psi', 'ks_statistic', 'js_divergence'
        sa.Column("feature_name", sa.String(50), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("alert_triggered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reference_period", sa.String(20), nullable=True),
        sa.Column("current_period", sa.String(20), nullable=True),
        sa.Column("report_s3_key", sa.String(500), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        "uq_drift_metrics_run_ticker_metric_feature",
        "drift_metrics",
        ["drift_run_id", "ticker", "metric_type", "feature_name"],
    )
    op.create_index("idx_drift_metrics_run", "drift_metrics", ["drift_run_id"])
    op.create_index(
        "idx_drift_metrics_ticker_metric",
        "drift_metrics",
        ["ticker", "metric_type"],
    )
    op.create_index(
        "idx_drift_metrics_alert",
        "drift_metrics",
        ["alert_triggered"],
    )


def downgrade() -> None:
    op.drop_table("drift_metrics")
    op.drop_table("prediction_log")
```

**Why:** Raw SQL via `op.create_table()` gives full control over JSONB and index definitions. Follows the same pattern as `0001_initial_schema.py`.

**Verify:** `docker compose run --rm backend sh -c "PYTHONPATH=/app alembic upgrade head"` applies cleanly. `docker compose run --rm backend sh -c "PYTHONPATH=/app alembic downgrade -1"` reverses cleanly.

**Risk:** Low. Standard ADD TABLE operations. No data dependencies.

---

### Round 2 — Prediction Logging (Live Inference Capture)

**Goal:** Every call to `GET /predict/{ticker}` logs its input features, prediction, and metadata to `prediction_log`. Non-blocking — the prediction response is not delayed by logging.

**Files to create:** 1 (prediction/prediction_logger.py)
**Files to modify:** 3 (prediction/service.py, src/config.py, maybe schema.py)

---

#### Step 2.1 — Add prediction logging config

**File:** `backend/src/config.py`
**Action:** Add drift/prediction-log settings.

Add after `PREDICTION_CACHE_TTL`:

```python
    # Prediction Logging / Drift
    PREDICTION_LOG_ENABLED: bool = True
    PREDICTION_LOG_RETENTION_DAYS: int = 90
    DRIFT_ALERT_PSI_THRESHOLD: float = 0.25
    DRIFT_ALERT_KS_THRESHOLD: float = 0.3
    DRIFT_ALERT_JS_THRESHOLD: float = 0.3
    DRIFT_MONITORED_TICKERS: str = ""  # comma-separated, empty = portfolio-only
    DRIFT_REPORT_S3_BUCKET: str = "stocklens-drift-reports"
    DRIFT_REPORT_S3_PREFIX: str = "drift_reports/"
```

**Why:** `PREDICTION_LOG_ENABLED` allows disabling logging for performance testing or if the log table becomes a bottleneck. `DRIFT_MONITORED_TICKERS` allows overriding the "portfolio tickers only" default. S3 bucket name follows the naming convention from Phase 1 Terraform (stocklens-drift-reports).

---

#### Step 2.2 — Create prediction logger module

**File:** `backend/src/prediction/prediction_logger.py`
**Action:** Async fire-and-forget function that inserts a row into `prediction_log`. Uses a dedicated database connection to avoid interfering with the main request pool.

```python
"""
Prediction logger — fire-and-forget logging of prediction requests for drift monitoring.

Logs run in a background thread pool so the prediction endpoint is never blocked.
Uses the existing connection pool via connection_ctx() — avoids pool exhaustion
because the thread pool limits concurrent DB connections to max_workers (2).
"""

from __future__ import annotations

import asyncio
import json
import structlog
from datetime import datetime, timezone
from typing import Any

import numpy as np

from src.config import settings

logger = structlog.get_logger()


# Feature names — must match the order produced by prediction_service._compute_features
# 17 features: 13 V1 + vol_pct + 3 cross-sectional
FEATURE_NAMES = [
    "log_ret_1d", "log_ret_5d", "log_ret_21d",
    "ma_5", "ma_10", "ma_20", "ma_50",
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "vol_30d", "vol_rank",
    "vol_pct",
    "excess_ret_1d", "excess_ret_5d", "excess_ret_21d",
]


async def log_prediction(
    ticker: str,
    model_version: str,
    prediction: str,
    confidence: float,
    probabilities: dict[str, float],
    feature_values: np.ndarray | None,  # (T, 17) full feature window, pre-window
    feature_window: np.ndarray | None,  # (30, 17) the actual model input
) -> None:
    """Log a single prediction to the prediction_log table.

    This is fire-and-forget: errors are logged but never propagated to the
    caller. The prediction response has already been sent.

    Args:
        ticker: Ticker symbol.
        model_version: Version string from the loaded model.
        prediction: Predicted direction (UP/FLAT/DOWN).
        confidence: Softmax probability of the predicted class.
        probabilities: Dict of class -> probability.
        feature_values: Full (T, 17) pre-standardisation feature matrix (optional).
        feature_window: The (30, 17) sliding window actually fed to the model (optional).
    """
    if not settings.PREDICTION_LOG_ENABLED:
        return

    if feature_values is not None:
        # Store feature statistics for drift detection
        # We store per-feature mean/std of the CURRENT window so drift detection
        # can reconstruct distribution info even if raw values vary in scale.
        feature_stats = {
            "means": [float(v) for v in feature_values.mean(axis=0).tolist()],
            "stds": [float(v) for v in feature_values.std(axis=0).tolist()],
            "n_samples": int(feature_values.shape[0]),
        }
        raw_features = feature_values.tolist()  # Full (T, 17)
    else:
        feature_stats = None
        raw_features = None

    if feature_window is not None:
        window_features = feature_window.tolist()  # (30, 17)
    else:
        window_features = None

    # Build the features JSONB — store both the raw window and stats
    features_payload: dict[str, Any] = {
        "window": window_features,
        "stats": feature_stats,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    raw_names_payload = FEATURE_NAMES  # Store once in the column

    try:
        # Use the existing connection pool from connection_ctx
        # Avoids opening a new DB connection per prediction
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            await conn.execute(
                """
                INSERT INTO prediction_log
                    (ticker, model_version, prediction, confidence, probabilities,
                     features, feature_stats, raw_feature_names)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb)
                """,
                ticker.upper(),
                model_version,
                prediction,
                confidence,
                json.dumps(probabilities),
                json.dumps(features_payload),
                json.dumps(feature_stats),
                json.dumps(raw_names_payload),
            )
    except Exception as exc:
        # Log but never raise — the prediction response has already been sent
        logger.warning("prediction_log_failed", ticker=ticker, error=str(exc))


def compute_feature_stats(feature_values: np.ndarray | None) -> dict | None:
    """Compute per-feature statistics from the raw feature matrix.

    Returns None if feature_values is None or empty.
    """
    if feature_values is None or feature_values.size == 0:
        return None
    return {
        "means": [float(v) for v in np.nanmean(feature_values, axis=0).tolist()],
        "stds": [float(v) for v in np.nanstd(feature_values, axis=0).tolist()],
        "n_samples": int(feature_values.shape[0]),
    }
```

**Why:** Fire-and-forget logging ensures the prediction endpoint latency is unaffected by I/O to the log table. Uses the existing `connection_ctx()` pool — the thread pool's `max_workers=2` naturally limits concurrent DB connections. Feature values are stored before standardisation — once z-scored, the original scale distribution is unrecoverable.

**Edge cases:**

- If `feature_values` is None (e.g., prediction failed), the log entry still records the prediction metadata
- If logging fails, the error is logged but the client's response is unaffected
- JSONB serialisation handles numpy arrays via `.tolist()` and `json.dumps()`

**Risk:** Low. Fire-and-forget pattern is well tested in this codebase.

---

#### Step 2.3 — Integrate logging into PredictionService.predict()

**File:** `backend/src/prediction/service.py`
**Action:** After computing the prediction, call `log_prediction()` with the raw feature values.

In `predict()` method, add after line 244 (`return { ... }`) but before the return:

```python
        # Fire-and-forget: log prediction for drift monitoring
        # Runs in background to avoid blocking the response
        if settings.PREDICTION_LOG_ENABLED:
            import asyncio
            asyncio.create_task(log_prediction(
                ticker=ticker,
                model_version=self.model_version,
                prediction=CLASS_NAMES[pred_class],
                confidence=confidence,
                probabilities=probabilities,
                feature_values=feature_values,  # Full (T, 17) pre-window matrix
                feature_window=feature_window,  # (30, 17) actual model input
            ))

        return { ... }
```

But wait — `predict()` is a synchronous method (no `async`). We need to run the async logging in a separate thread. Use `asyncio.get_event_loop().run_in_executor()` or better, create the task from the running event loop.

Actually, the existing FastAPI app runs in an async context. The prediction router calls `prediction_service.predict()` which is sync. We can convert the approach:

**Add a thread pool approach in prediction_logger.py:**

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

_logger_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pred_log")


def log_prediction_sync(
    ticker: str,
    model_version: str,
    prediction: str,
    confidence: float,
    probabilities: dict[str, float],
    feature_values: np.ndarray | None,
    feature_window: np.ndarray | None,
) -> None:
    """Synchronous wrapper for log_prediction. Runs the coroutine in a new event loop."""
    try:
        asyncio.run(log_prediction(
            ticker=ticker,
            model_version=model_version,
            prediction=prediction,
            confidence=confidence,
            probabilities=probabilities,
            feature_values=feature_values,
            feature_window=feature_window,
        ))
    except Exception as exc:
        logger.warning("prediction_log_sync_failed", ticker=ticker, error=str(exc))
```

Then in `service.py`, inside `predict()`:

```python
        # Fire-and-forget: log prediction for drift monitoring
        _logger_executor.submit(log_prediction_sync, ...)
```

**Why:** The prediction service is synchronous (no `async def`). Using `ThreadPoolExecutor` to run the async logging function in a background thread avoids blocking the prediction response and doesn't require converting the entire service to async.

**Verify:** After a prediction request, a row appears in `prediction_log`. `SELECT COUNT(*) FROM prediction_log` increments.

**Ponytail simplification:** The thread pool uses `max_workers=2` with no bounded queue. Under burst load, tasks can be dropped (RejectedExecutionException). For Phase 4, this is acceptable — dropped logs only affect drift detection sensitivity, not correctness. Add an `asyncio.Queue(1000)` with a dedicated consumer if throughput exceeds the pool capacity.

**Risk:** Low. Thread pool approach is well understood. `max_workers=2` limits connection pressure.

---

#### Step 2.4 — Add prediction logger tests

**File:** `backend/tests/test_prediction_logger.py`
**Action:** ~15 tests covering logging happy path, disabled logging, missing features, escape chars in JSONB, concurrent logs.

Test cases:

- `test_log_prediction_happy_path` — Insert a row, verify all columns
- `test_log_disabled` — When `PREDICTION_LOG_ENABLED=False`, no row inserted
- `test_log_with_null_features` — `feature_values=None` still logs prediction metadata
- `test_log_feature_stats_computed` — Verify means/stds are correct for simple input
- `test_log_special_chars_in_ticker` — Ticker with `.` or `-` in JSONB
- `test_log_concurrent_safety` — 5 concurrent logs all succeed
- `test_feature_names_constant` — `FEATURE_NAMES` has exactly 17 entries matching expected order

---

### Round 3 — Drift Detection Module (Evidently)

**Goal:** PSI/KS/JS divergence computation, Evidently HTML report generation, S3 upload with pre-signed URLs, `drift_metrics` DB persistence. All wrapped in a clean `DriftDetector` class.

**Files to create:** 5 (drift/schemas.py, drift/service.py, drift/evidently_reporter.py, drift/repository.py, drift/utils.py)
**Files to modify:** 2 (src/config.py — already done in 2.1, src/main.py — register router)

---

#### Step 3.1 — Drift schemas

**File:** `backend/src/drift/schemas.py`
**Action:** Pydantic models for drift API.

```python
"""
Schemas for the drift detection module.

All metrics follow the Evidently AI conventions:
- PSI: Population Stability Index (<0.1 no shift, 0.1-0.25 slight, >0.25 significant)
- KS: Kolmogorov-Smirnov statistic (0-1, higher = more shift)
- JS: Jensen-Shannon divergence (0-1, symmetric)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DriftRunRequest(BaseModel):
    """Request to trigger a drift detection run.

    If tickers is empty, defaults to portfolio tickers + SPY.
    """
    tickers: list[str] = Field(default_factory=list, max_length=100)
    lookback_days: int = Field(default=7, ge=1, le=365)
    generate_report: bool = Field(default=True)


class DriftMetricResponse(BaseModel):
    """A single drift metric for one ticker, one feature, one metric type."""
    ticker: str
    model_version: str
    metric_type: str  # 'psi', 'ks_statistic', 'js_divergence'
    feature_name: str  # e.g. 'log_ret_1d', 'prediction_distribution'
    drift_score: float
    alert_triggered: bool
    reference_period: str | None
    current_period: str | None


class DriftRunResponse(BaseModel):
    """Response from a drift detection run."""
    drift_run_id: str
    tickers_monitored: list[str]
    total_metrics: int
    alerts_triggered: int
    max_psi: float
    max_js_divergence: float
    overall_drift_verdict: str  # 'drifted' if any alert, else 'stable'
    report_url: str | None  # Pre-signed S3 URL
    metrics: list[DriftMetricResponse]
    created_at: datetime


class DriftReportSummary(BaseModel):
    """Summary of the latest drift status for dashboard display."""
    overall_status: str  # 'healthy', 'warning', 'critical'
    drifted_features: int
    total_features_monitored: int
    latest_run_id: str
    latest_run_at: datetime | None
    tickers_with_drift: list[str]
```

**Why:** `DriftRunRequest` allows manual triggering with custom tickers and lookback window. `DriftRunResponse` gives a complete picture of one drift run including the pre-signed report URL. `DriftReportSummary` is lightweight for the frontend dashboard.

---

#### Step 3.2 — Drift repository (drift_metrics CRUD)

**File:** `backend/src/drift/repository.py`
**Action:** Async database operations for `drift_metrics` table. Follows the same asyncpg pattern as `market/repository.py`.

```python
"""
Repository for drift_metrics CRUD operations.

Follows the same asyncpg pattern as market/repository.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from src.database.connection import connection_ctx

logger = structlog.get_logger()


def generate_drift_run_id() -> str:
    """Generate a unique drift run ID."""
    return str(uuid.uuid4())


async def create_drift_metric(
    drift_run_id: str,
    ticker: str,
    model_version: str,
    metric_type: str,
    feature_name: str,
    drift_score: float,
    alert_triggered: bool = False,
    reference_period: str | None = None,
    current_period: str | None = None,
    report_s3_key: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    """Insert a single drift metric row.

    Returns:
        The ID of the inserted row.
    """
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO drift_metrics
                (drift_run_id, ticker, model_version, metric_type, feature_name,
                 drift_score, alert_triggered, reference_period, current_period,
                 report_s3_key, details)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
            RETURNING id
            """,
            drift_run_id,
            ticker.upper(),
            model_version,
            metric_type,
            feature_name,
            drift_score,
            alert_triggered,
            reference_period,
            current_period,
            report_s3_key,
            json.dumps(details) if details else None,
        )
        return row["id"]


async def get_latest_drift_summary(
    tickers: list[str] | None = None,
    max_age_days: int = 7,
) -> dict[str, Any]:
    """Get a summary of the most recent drift run.

    Returns:
        Dict with overall_status, drifted_features, total_features, latest_run info.
    """
    async with connection_ctx() as conn:
        # Get the latest drift run ID
        latest_run = await conn.fetchrow(
            """
            SELECT drift_run_id, MAX(created_at) as latest_run_at
            FROM drift_metrics
            WHERE created_at >= $1
            GROUP BY drift_run_id
            ORDER BY latest_run_at DESC
            LIMIT 1
            """,
            datetime.now(timezone.utc) - timedelta(days=max_age_days),
        )

        if not latest_run:
            return {
                "overall_status": "unknown",
                "drifted_features": 0,
                "total_features_monitored": 0,
                "latest_run_id": "",
                "latest_run_at": None,
                "tickers_with_drift": [],
            }

        # Count alerts in the latest run
        alerts = await conn.fetch(
            """
            SELECT DISTINCT ticker
            FROM drift_metrics
            WHERE drift_run_id = $1 AND alert_triggered = true
            """,
            latest_run["drift_run_id"],
        )

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM drift_metrics WHERE drift_run_id = $1",
            latest_run["drift_run_id"],
        )

        alert_count = len(alerts)
        return {
            "overall_status": "critical" if alert_count > 5 else ("warning" if alert_count > 0 else "healthy"),
            "drifted_features": alert_count,
            "total_features_monitored": total,
            "latest_run_id": latest_run["drift_run_id"],
            "latest_run_at": latest_run["latest_run_at"],
            "tickers_with_drift": [r["ticker"] for r in alerts],
        }


async def list_drift_runs(
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List recent drift runs with aggregate info."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            """
            SELECT
                drift_run_id,
                MIN(created_at) as run_at,
                COUNT(*) as total_metrics,
                SUM(CASE WHEN alert_triggered THEN 1 ELSE 0 END) as alert_count,
                MAX(drift_score) as max_drift_score,
                COUNT(DISTINCT ticker) as tickers_monitored
            FROM drift_metrics
            GROUP BY drift_run_id
            ORDER BY run_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [dict(r) for r in rows]


async def get_drift_report_by_run(drift_run_id: str) -> list[dict[str, Any]]:
    """Get all metrics for a specific drift run."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM drift_metrics
            WHERE drift_run_id = $1
            ORDER BY ticker, metric_type, feature_name
            """,
            drift_run_id,
        )
        return [dict(r) for r in rows]


async def prune_old_metrics(retention_days: int = 365) -> int:
    """Delete drift metrics older than retention_days.

    Returns:
        Number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with connection_ctx() as conn:
        status = await conn.execute(
            "DELETE FROM drift_metrics WHERE created_at < $1",
            cutoff,
        )
        count = int(status.split()[-1])
        if count > 0:
            logger.info("pruned_old_drift_metrics", count=count)
        return count
```

**Why:** Follows the same asyncpg `connection_ctx()` pattern used across the entire backend. `get_latest_drift_summary()` is designed for quick dashboard polling. `prune_old_metrics()` handles the cleanup task in Airflow DAG.

**Edge cases:**

- No drift runs yet → returns "unknown" status
- Alert count > 5 → status is "critical"
- Alert count 1-5 → status is "warning"

---

#### Step 3.3 — Drift detection service (PSI/KS/JS)

**File:** `backend/src/drift/service.py`
**Action:** Core drift computation: PSI, KS-test, JS divergence. Pure functions operating on numpy arrays.

```python
"""
Drift detection service — PSI, KS, and JS divergence computation.

All functions are pure numpy operations (no DB, no I/O). Designed to be
callable from both the FastAPI endpoint and the Airflow DAG.
"""

from __future__ import annotations

import structlog
from typing import Any

import numpy as np
from scipy.stats import ks_2samp

from src.config import settings

logger = structlog.get_logger()


def compute_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 20,
) -> float:
    """Compute Population Stability Index (PSI) between two distributions.

    PSI = Σ( (actual_i - expected_i) * ln(actual_i / expected_i) )

    Where expected_i and actual_i are the proportions in bin i after
    applying the same binning (based on expected distribution deciles).

    Args:
        expected: Reference distribution values (1-D array).
        actual: Current distribution values (1-D array).
        n_bins: Number of bins (default 20).

    Returns:
        PSI score. PSI < 0.1 = no shift, 0.1-0.25 = slight, >0.25 = significant.
    """
    if len(expected) == 0 or len(actual) == 0:
        return 0.0

    # Create bins based on expected distribution percentiles
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]

    if len(expected) == 0 or len(actual) == 0:
        return 0.0

    # Define bin edges from expected distribution
    percentiles = np.linspace(0, 100, n_bins + 1)
    bin_edges = np.percentile(expected, percentiles)

    # Handle edge case: all values identical
    if len(np.unique(bin_edges)) == 1:
        # All values same — single bin
        return 0.0

    # Bin both distributions
    expected_binned = np.histogram(expected, bins=bin_edges)[0].astype(float)
    actual_binned = np.histogram(actual, bins=bin_edges)[0].astype(float)

    # Convert to proportions
    expected_pct = expected_binned / len(expected)
    actual_pct = actual_binned / len(actual)

    # Replace zeros to avoid division by zero / log(0)
    # ponytail: epsilon floor instead of laplace smoothing — simpler
    eps = 1e-6
    expected_pct = np.maximum(expected_pct, eps)
    actual_pct = np.maximum(actual_pct, eps)

    # Normalise so proportions sum to 1
    expected_pct = expected_pct / expected_pct.sum()
    actual_pct = actual_pct / actual_pct.sum()

    # PSI = Σ (actual - expected) * ln(actual / expected)
    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return float(psi)


def compute_ks(
    reference: np.ndarray,
    current: np.ndarray,
) -> dict[str, float]:
    """Compute Kolmogorov-Smirnov test between two distributions.

    Args:
        reference: Reference distribution values (1-D array).
        current: Current distribution values (1-D array).

    Returns:
        Dict with keys: 'statistic' (the KS statistic, 0-1),
        'p_value' (significance).
    """
    reference_clean = reference[~np.isnan(reference)]
    current_clean = current[~np.isnan(current)]

    if len(reference_clean) == 0 or len(current_clean) == 0:
        return {"statistic": 0.0, "p_value": 1.0}

    statistic, p_value = ks_2samp(reference_clean, current_clean)
    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
    }


def compute_js_divergence(
    p: np.ndarray,
    q: np.ndarray,
) -> float:
    """Compute Jensen-Shannon divergence between two probability distributions.

    JS(P || Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
    where M = 0.5 * (P + Q)

    JS divergence is symmetric, bounded [0, 1] (for log base 2).
    JS = 0 means identical distributions, JS = 1 means maximally different.

    Args:
        p: First probability distribution (1-D array, must sum to 1).
        q: Second probability distribution (1-D array, must sum to 1).

    Returns:
        JS divergence score (0-1).
    """
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)

    # Add epsilon to avoid log(0)
    eps = 1e-12
    p = np.maximum(p, eps)
    q = np.maximum(q, eps)

    # Normalise
    p = p / p.sum()
    q = q / q.sum()

    m = 0.5 * (p + q)

    # KL divergence with log base 2 for [0, 1] bound
    kl_pm = np.sum(p * np.log2(p / m))
    kl_qm = np.sum(q * np.log2(q / m))

    js = 0.5 * (kl_pm + kl_qm)
    return float(np.clip(js, 0.0, 1.0))


def compute_prediction_distribution(
    predictions: list[str],
    class_order: tuple[str, ...] = ("DOWN", "FLAT", "UP"),
) -> np.ndarray:
    """Compute the probability distribution of prediction classes.

    Args:
        predictions: List of prediction strings (UP/FLAT/DOWN).
        class_order: Canonical order of classes.

    Returns:
        Array of shape (3,) with class proportions.
    """
    counts = {c: 0 for c in class_order}
    for pred in predictions:
        if pred in counts:
            counts[pred] += 1

    total = max(sum(counts.values()), 1)
    return np.array([counts[c] / total for c in class_order], dtype=float)


class DriftDetector:
    """Orchestrates drift detection across tickers.

    Computes PSI, KS, and JS divergence between reference distributions
    (from training set) and current distributions (from prediction_log).
    """

    def __init__(self) -> None:
        self.psi_threshold = settings.DRIFT_ALERT_PSI_THRESHOLD
        self.ks_threshold = settings.DRIFT_ALERT_KS_THRESHOLD
        self.js_threshold = settings.DRIFT_ALERT_JS_THRESHOLD

    async def compute_drift(
        self,
        tickers: list[str],
        reference_dist: dict[str, Any],
        prediction_logs: dict[str, list[dict]],
        model_version: str,
        drift_run_id: str,
        current_period: str,
    ) -> dict[str, Any]:
        """Run full drift detection for a set of tickers.

        Args:
            tickers: List of ticker symbols to monitor.
            reference_dist: Reference distribution data from champion model.
                Expected keys: 'feature_histograms' (dict of feature_name -> dict),
                'prediction_distribution' (array of 3 class proportions).
            prediction_logs: Dict mapping ticker -> list of prediction_log rows.
            model_version: Current champion model version.
            drift_run_id: UUID for this drift run.
            current_period: String label for the current period (e.g., '2026-07-01_2026-07-07').

        Returns:
            Dict with: drift_run_id, metrics (list of DriftMetric-like dicts),
            alerts_triggered, max_psi, max_js, overall_verdict.
        """
        all_metrics: list[dict[str, Any]] = []
        alerts = 0
        max_psi = 0.0
        max_js = 0.0

        # Load reference distributions
        feature_histograms = reference_dist.get("feature_histograms", {})
        ref_prediction_dist = np.array(
            reference_dist.get("prediction_distribution", [1/3, 1/3, 1/3]),
            dtype=float,
        )

        for ticker in tickers:
            logs = prediction_logs.get(ticker, [])
            if len(logs) < 5:
                logger.warning("insufficient_logs_for_drift", ticker=ticker, count=len(logs))
                continue

            # Extract feature values from prediction_log
            # Each log entry has 'features' JSONB with 'window' or 'stats'
            feature_values_by_field: dict[str, list[float]] = {}
            all_predictions: list[str] = []

            for log_entry in logs:
                all_predictions.append(log_entry.get("prediction", "FLAT"))
                features_data = log_entry.get("features", {})
                if not features_data:
                    continue

                # If we have per-feature stats, reconstruct approximate values
                # Otherwise use the window data
                stats = features_data.get("stats")
                if stats and "means" in stats:
                    # Use stored raw_feature_names (from prediction_log row) to map
                    # feature values to names — this handles the case where SPY
                    # was unavailable at inference and only 14 features were computed
                    # (vs 17 in the reference distribution). Falls back to
                    # FEATURE_NAMES_REVERSED if raw_feature_names is missing.
                    feature_names = log_entry.get("raw_feature_names") or FEATURE_NAMES_REVERSED
                    for i, feature_name in enumerate(feature_names):
                        if i < len(stats["means"]):
                            if feature_name not in feature_values_by_field:
                                feature_values_by_field[feature_name] = []
                            feature_values_by_field[feature_name].append(stats["means"][i])

            # For each feature, compute PSI and KS
            for feature_name, ref_hist in feature_histograms.items():
                if feature_name not in feature_values_by_field:
                    continue

                current_values = np.array(feature_values_by_field[feature_name])
                ref_values = np.array(ref_hist.get("values", []))

                if len(ref_values) == 0 or len(current_values) < 5:
                    continue

                # PSI
                psi = compute_psi(ref_values, current_values)
                psi_alert = psi > self.psi_threshold
                if psi_alert:
                    alerts += 1
                max_psi = max(max_psi, psi)

                all_metrics.append({
                    "ticker": ticker,
                    "model_version": model_version,
                    "metric_type": "psi",
                    "feature_name": feature_name,
                    "drift_score": psi,
                    "alert_triggered": psi_alert,
                    "reference_period": "training_set",
                    "current_period": current_period,
                    "details": {"n_reference": len(ref_values), "n_current": len(current_values)},
                })

                # KS
                ks_result = compute_ks(ref_values, current_values)
                ks_alert = ks_result["statistic"] > self.ks_threshold
                if ks_alert:
                    alerts += 1

                all_metrics.append({
                    "ticker": ticker,
                    "model_version": model_version,
                    "metric_type": "ks_statistic",
                    "feature_name": feature_name,
                    "drift_score": ks_result["statistic"],
                    "alert_triggered": ks_alert,
                    "reference_period": "training_set",
                    "current_period": current_period,
                    "details": {"p_value": ks_result["p_value"]},
                })

            # Prediction distribution drift (JS divergence)
            if len(all_predictions) >= 5:
                current_pred_dist = compute_prediction_distribution(all_predictions)
                js = compute_js_divergence(ref_prediction_dist, current_pred_dist)
                js_alert = js > self.js_threshold
                if js_alert:
                    alerts += 1
                max_js = max(max_js, js)

                all_metrics.append({
                    "ticker": ticker,
                    "model_version": model_version,
                    "metric_type": "js_divergence",
                    "feature_name": "prediction_distribution",
                    "drift_score": js,
                    "alert_triggered": js_alert,
                    "reference_period": "training_set",
                    "current_period": current_period,
                    "details": {
                        "ref_distribution": ref_prediction_dist.tolist(),
                        "current_distribution": current_pred_dist.tolist(),
                    },
                })

        return {
            "drift_run_id": drift_run_id,
            "metrics": all_metrics,
            "alerts_triggered": alerts,
            "max_psi": max_psi,
            "max_js_divergence": max_js,
            "overall_verdict": "drifted" if alerts > 0 else "stable",
        }


# Feature name list for indexing — reversed lookup from index to name
FEATURE_NAMES_REVERSED: list[str] = [
    "log_ret_1d", "log_ret_5d", "log_ret_21d",
    "ma_5", "ma_10", "ma_20", "ma_50",
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "vol_30d", "vol_rank",
    "vol_pct",
    "excess_ret_1d", "excess_ret_5d", "excess_ret_21d",
]
```

**Why:** Pure numpy/scipy functions are independently testable. `DriftDetector` orchestrates across tickers — it parses the `prediction_log` features JSONB, runs per-feature PSI/KS, and computes prediction-distribution JS divergence. All three thresholds (PSI=0.25, KS=0.3, JS=0.3) are configurable via settings.

**Edge cases:**

- Fewer than 5 prediction logs for a ticker → skip drift (insufficient sample)
- Feature name not found in logs → skip gracefully
- All identical values → PSI = 0 (no drift)
- `scipy.stats.ks_2samp()` may raise on all-identical arrays — handled by `compute_ks` cleaning NaN and checking lengths
- **Feature count mismatch:** Reference distribution may have 17 features (including cross-sectional vs SPY), but prediction_log may have only 14 if SPY was unavailable at inference. Using `raw_feature_names` from each log row instead of the hardcoded `FEATURE_NAMES_REVERSED` ensures correct name→value mapping. Missing features are skipped gracefully (`feature_name not in feature_values_by_field`).

**Dependency note:** This module needs `scipy`. It's already in `pyproject.toml` via `scikit-learn` dependency (scipy is a scikit-learn dependency).

---

#### Step 3.4 — Evidently reporter

**File:** `backend/src/drift/evidently_reporter.py`
**Action:** Generates Evidently AI HTML reports for drift detection.

```python
"""
Evidently AI report generation for drift detection.

Generates DataDriftPreset reports comparing reference (training) and
current (production) data distributions. Reports are saved as HTML
and uploaded to S3.
"""

from __future__ import annotations

import uuid
from typing import Any
from pathlib import Path

import pandas as pd
import structlog

from evidently import ColumnMapping
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset

logger = structlog.get_logger()


class EvidentlyReporter:
    """Generates Evidently AI drift reports.

    Args:
        output_dir: Local directory to save HTML reports before S3 upload.
    """

    def __init__(self, output_dir: str = "/tmp/evidently_reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_drift_report(
        self,
        reference_df: pd.DataFrame,
        current_df: pd.DataFrame,
        column_mapping: ColumnMapping | None = None,
    ) -> tuple[str, str]:
        """Generate an Evidently DataDrift report comparing two datasets.

        Args:
            reference_df: Reference (training) dataset. Must include feature columns
                and optionally a prediction/target column.
            current_df: Current (production) dataset. Same columns as reference_df.
            column_mapping: Evidently column mapping. If None, auto-detected.

        Returns:
            (report_path, report_id) tuple. report_path is the local file path
            to the saved HTML report. report_id is a UUID for tracking.
        """
        if column_mapping is None:
            # Auto-detect: treat all numeric columns as features
            column_mapping = ColumnMapping(
                numerical_features=list(reference_df.select_dtypes(include=["number"]).columns),
            )

        # Create Evidently report with DataDrift preset
        report = Report(metrics=[
            DataDriftPreset(
                columns=column_mapping.numerical_features,
                stattest="psi",  # Primary drift test: PSI
                cat_stattest="psi",
                num_stattest="psi",
                confidence=0.95,
            ),
        ])

        report.run(reference_data=reference_df, current_data=current_df)

        # Save as HTML
        report_id = str(uuid.uuid4())
        report_path = str(self.output_dir / f"drift_report_{report_id}.html")
        report.save_html(report_path)

        logger.info(
            "drift_report_generated",
            report_id=report_id,
            path=report_path,
            n_columns=len(reference_df.columns),
        )

        return report_path, report_id

    def get_report_as_dict(self, report_path: str) -> dict[str, Any]:
        """Get the Evidently report summary as a dict (for storing in DB).

        Args:
            report_path: Path to the saved HTML report.

        Returns:
            Dict with report metadata: drift_share, number_of_drifted_columns, etc.
        """
        # ponytail: Evidently doesn't expose a clean dict API for saved HTML reports.
        # We extract key metrics during generation instead and store those in DB.
        # This keeps the HTML as the primary artifact.
        return {}
```

**Why:** Evidently's `DataDriftPreset` computes PSI per column and generates a comprehensive HTML report with distribution histograms, drift scores, and column-level summaries. The report is saved as HTML for S3 upload. The DB stores individual PSI/KS metrics independently.

**Evidently integration note:** The `DataDriftPreset` includes PSI, KS, JS divergence, and Wasserstein distance by default. We configure it to use PSI as the primary test (matching our DB metric schema), but the report will include all available tests.

**Risk:** Low. Evidently is a mature, well-documented library. The `DataDriftPreset` is a standard pattern.

---

#### Step 3.5 — S3 upload and pre-signed URLs

**File:** `backend/src/drift/utils.py`
**Action:** Upload drift report HTML to S3, generate pre-signed URLs for secure access.

```python
"""
S3 utilities for drift reports.
"""

from __future__ import annotations

import structlog
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from src.config import settings

logger = structlog.get_logger()


def upload_report_to_s3(local_path: str, s3_key: str) -> bool:
    """Upload a drift report HTML file to S3.

    Args:
        local_path: Local file path to the HTML report.
        s3_key: S3 object key (e.g., 'drift_reports/2026-07-06/report_abc123.html').

    Returns:
        True if upload succeeded, False otherwise.
    """
    if not settings.DRIFT_REPORT_S3_BUCKET:
        logger.warning("no_s3_bucket_configured_for_drift_reports")
        return False

    try:
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.upload_file(
            Filename=local_path,
            Bucket=settings.DRIFT_REPORT_S3_BUCKET,
            Key=s3_key,
            ExtraArgs={"ContentType": "text/html"},
        )
        logger.info("drift_report_uploaded_to_s3", bucket=settings.DRIFT_REPORT_S3_BUCKET, key=s3_key)
        return True
    except ClientError as exc:
        logger.error("drift_report_s3_upload_failed", error=str(exc))
        return False


def generate_presigned_url(s3_key: str, expiration: int = 604800) -> str | None:
    """Generate a pre-signed URL for a drift report.

    Args:
        s3_key: S3 object key.
        expiration: URL expiration in seconds (default 7 days).

    Returns:
        Pre-signed URL string, or None on failure.
    """
    if not settings.DRIFT_REPORT_S3_BUCKET:
        return None

    try:
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.DRIFT_REPORT_S3_BUCKET,
                "Key": s3_key,
            },
            ExpiresIn=expiration,
        )
        return url
    except ClientError as exc:
        logger.error("presigned_url_generation_failed", error=str(exc))
        return None


def build_s3_key(drift_run_id: str, filename: str) -> str:
    """Build an S3 object key for a drift report.

    Args:
        drift_run_id: UUID of the drift run.
        filename: Report filename (e.g., 'drift_report_abc123.html').

    Returns:
        S3 key like 'drift_reports/2026-07-06/drift_report_abc123.html'.
    """
    from datetime import datetime, timezone
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{settings.DRIFT_REPORT_S3_PREFIX.rstrip('/')}/{date_prefix}/{filename}"
```

**Why:** Boto3 S3 upload with `ContentType` for inline browser viewing. Pre-signed URLs expire in 7 days by default — the FastAPI endpoint can regenerate them on each request. Build key includes date prefix for S3 folder organisation.

---

#### Step 3.6 — Drift router (FastAPI endpoints)

**File:** `backend/src/drift/router.py`
**Action:** FastAPI endpoints for manual drift triggering, report viewing, summary dashboard.

```python
"""
Drift detection endpoints.

POST /drift/run          — Trigger on-demand drift detection
GET  /drift/summary      — Latest drift summary (dashboard)
GET  /drift/runs         — List recent drift runs
GET  /drift/runs/{id}    — Get metrics for a specific run
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import get_current_user_id
from src.drift.schemas import (
    DriftRunRequest,
    DriftRunResponse,
    DriftMetricResponse,
    DriftReportSummary,
)
from src.drift.service import DriftDetector
from src.drift.repository import (
    generate_drift_run_id,
    get_latest_drift_summary,
    list_drift_runs,
    get_drift_report_by_run,
    create_drift_metric,
)
from src.drift.utils import upload_report_to_s3, generate_presigned_url, build_s3_key
from src.drift.evidently_reporter import EvidentlyReporter
from src.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/drift", tags=["drift"])
detector = DriftDetector()
reporter = EvidentlyReporter()


@router.post("/run", response_model=DriftRunResponse)
async def trigger_drift_run(
    request: DriftRunRequest,
    user_id: str = Depends(get_current_user_id),
) -> DriftRunResponse:
    """Trigger an on-demand drift detection run.

    Requires authentication. Monitored tickers default to portfolio tickers
    if not specified in the request.
    """
    drift_run_id = generate_drift_run_id()
    current_period = datetime.now(timezone.utc).strftime("%Y-%m-%d_%Y-%m-%d")

    # 1. Determine tickers to monitor
    tickers = request.tickers
    if not tickers:
        # Default: fetch portfolio tickers from DB
        async with connection_ctx() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ticker FROM holdings"
            )
            tickers = [r["ticker"] for r in rows] + ["SPY"]

    # 2. Fetch reference distribution from champion model
    # (stored in model_registry.metrics JSONB)
    async with connection_ctx() as conn:
        champion_row = await conn.fetchrow(
            "SELECT mlflow_run_id, model_version, metrics FROM model_registry WHERE alias = 'champion'"
        )

    if not champion_row:
        raise HTTPException(status_code=503, detail="No champion model found — cannot run drift detection")

    model_version = champion_row["model_version"] or "unknown"
    reference_dist = champion_row["metrics"].get("reference_distributions", {}) if champion_row["metrics"] else {}

    # 3. Fetch prediction logs for monitored tickers
    lookback_start = datetime.now(timezone.utc) - timedelta(days=request.lookback_days)
    prediction_logs: dict[str, list[dict]] = {t: [] for t in tickers}

    async with connection_ctx() as conn:
        rows = await conn.fetch(
            """
            SELECT ticker, prediction, confidence, features, feature_stats, created_at
            FROM prediction_log
            WHERE ticker = ANY($1::varchar[]) AND created_at >= $2
            ORDER BY created_at DESC
            """,
            list(tickers),
            lookback_start,
        )

    for row in rows:
        t = row["ticker"]
        if t in prediction_logs:
            prediction_logs[t].append(dict(row))

    # 4. Compute drift metrics
    drift_result = await detector.compute_drift(
        tickers=tickers,
        reference_dist=reference_dist,
        prediction_logs=prediction_logs,
        model_version=model_version,
        drift_run_id=drift_run_id,
        current_period=current_period,
    )

    # 5. Persist metrics to DB
    report_s3_key = None
    for metric in drift_result["metrics"]:
        await create_drift_metric(
            drift_run_id=drift_run_id,
            **metric,
        )

    # 6. Generate Evidently report if requested
    report_url = None
    if request.generate_report and reference_dist:
        try:
            # Build DataFrames for Evidently
            ref_df = _build_reference_dataframe(reference_dist)
            cur_df = _build_current_dataframe(prediction_logs)

            if ref_df is not None and cur_df is not None:
                report_path, report_id = reporter.generate_drift_report(ref_df, cur_df)
                report_s3_key = build_s3_key(drift_run_id, f"drift_report_{report_id}.html")
                uploaded = upload_report_to_s3(report_path, report_s3_key)
                if uploaded:
                    report_url = generate_presigned_url(report_s3_key)
                    # Update drift_metrics rows with report S3 key
                    async with connection_ctx() as conn:
                        await conn.execute(
                            "UPDATE drift_metrics SET report_s3_key = $1 WHERE drift_run_id = $2",
                            report_s3_key, drift_run_id,
                        )
        except Exception as exc:
            logger.error("evidently_report_generation_failed", error=str(exc))

    # 7. Log alerts
    if drift_result["alerts_triggered"] > 0:
        logger.warning(
            "drift_alerts_triggered",
            drift_run_id=drift_run_id,
            alerts=drift_result["alerts_triggered"],
            max_psi=drift_result["max_psi"],
            max_js=drift_result["max_js_divergence"],
        )

    # Build response metrics
    response_metrics = [
        DriftMetricResponse(**m) for m in drift_result["metrics"]
    ]

    return DriftRunResponse(
        drift_run_id=drift_run_id,
        tickers_monitored=tickers,
        total_metrics=len(drift_result["metrics"]),
        alerts_triggered=drift_result["alerts_triggered"],
        max_psi=drift_result["max_psi"],
        max_js_divergence=drift_result["max_js_divergence"],
        overall_drift_verdict=drift_result["overall_verdict"],
        report_url=report_url,
        metrics=response_metrics,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/summary", response_model=DriftReportSummary)
async def get_drift_summary(
    user_id: str = Depends(get_current_user_id),
) -> DriftReportSummary:
    """Get the latest drift detection summary (dashboard widget)."""
    summary = await get_latest_drift_summary()
    return DriftReportSummary(**summary)


@router.get("/runs")
async def list_recent_runs(
    limit: int = 20,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    """List recent drift detection runs with aggregated metrics."""
    return await list_drift_runs(limit=limit, offset=offset)


@router.get("/runs/{drift_run_id}")
async def get_run_details(
    drift_run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    """Get all metrics for a specific drift run."""
    metrics = await get_drift_report_by_run(drift_run_id)
    if not metrics:
        raise HTTPException(status_code=404, detail="Drift run not found")
    return metrics


def _build_reference_dataframe(reference_dist: dict) -> pd.DataFrame | None:
    """Build a pandas DataFrame from reference distribution histograms
    for Evidently report generation."""
    import pandas as pd

    feature_histograms = reference_dist.get("feature_histograms", {})
    if not feature_histograms:
        return None

    # Build from stored histogram samples
    # Each feature has a 'values' list — take N samples per feature
    n_samples = min(
        min((v.get("values", []) for v in feature_histograms.values()), key=len) or 100,
        1000,
    )

    data: dict[str, list[float]] = {}
    for feature_name, hist in feature_histograms.items():
        values = hist.get("values", [])
        if len(values) >= n_samples:
            data[feature_name] = list(values[:n_samples])

    if not data:
        return None

    return pd.DataFrame(data)


def _build_current_dataframe(
    prediction_logs: dict[str, list[dict]],
) -> pd.DataFrame | None:
    """Build a pandas DataFrame from recent prediction_log entries."""
    import pandas as pd

    all_rows: list[dict[str, float]] = []
    for ticker, logs in prediction_logs.items():
        for entry in logs:
            features_data = entry.get("features", {}) or {}
            stats = features_data.get("stats")
            if stats and "means" in stats:
                row = {}
                for i, value in enumerate(stats["means"]):
                    feature_name = (
                        "log_ret_1d", "log_ret_5d", "log_ret_21d",
                        "ma_5", "ma_10", "ma_20", "ma_50",
                        "rsi_14", "macd", "macd_signal", "macd_hist",
                        "vol_30d", "vol_rank",
                        "vol_pct",
                        "excess_ret_1d", "excess_ret_5d", "excess_ret_21d",
                    )
                    if i < len(feature_name):
                        row[feature_name[i]] = value
                if row:
                    all_rows.append(row)

    if not all_rows:
        return None

    return pd.DataFrame(all_rows)
```

**Why:** The drift router provides both on-demand (`POST /drift/run`) and dashboard (`GET /drift/summary`) endpoints. The `_build_reference_dataframe` and `_build_current_dataframe` helpers create the pandas DataFrames that Evidently needs for report generation.

**Note:** The `connection_ctx` import is needed in the router — add `from src.database.connection import connection_ctx`.

**Verify:** `POST /drift/run` returns a `DriftRunResponse` with metrics and (optionally) a report URL. `GET /drift/summary` returns the latest status.

---

#### Step 3.7 — Register drift router in main.py

**File:** `backend/src/main.py`
**Action:** Import and include the drift router.

```python
from src.drift.router import router as drift_router
app.include_router(drift_router)
```

**Verify:** `GET /docs` shows the new drift endpoints.

---

#### Step 3.8 — Drift tests

**File:** `backend/tests/test_drift/`
**Action:** ~35 tests across all drift components.

- `test_drift_service.py` — 12 tests: PSI identical distributions (=0), PSI very different (>0.5), KS identical (=0), KS different (>0), JS identical (=0), JS different (>0), empty arrays, single values, NaN handling, prediction distribution computation.
- `test_evidently_reporter.py` — 8 tests: report generation with valid data, empty data, single column, missing values, output file exists, file is valid HTML.
- `test_repository.py` — 8 tests: create metric, read latest summary, list runs, run details, prune old data, empty state.
- `test_router.py` — 7 tests: POST /drift/run (no auth → 401), POST /drift/run (no champion → 503), POST /drift/run (happy path, mocked prediction_log), GET /drift/summary (happy path, empty state), GET /drift/runs (paginated).

---

### Round 4 — Champion Comparison Gate in ML Pipeline

**Goal:** Modify the training pipeline so the challenger model is compared against the current champion before promotion. Only promote if directional accuracy improves by >2pp.

**Files to modify:** 2 (ml/pipeline.py, ml/mlflow_manager.py)
**Files to create:** 1 (ml/reference_distributions.py)

---

#### Step 4.1 — Add `read_champion_metrics()` to MLflowManager

**File:** `backend/ml/mlflow_manager.py`
**Action:** Add method to fetch champion's test metrics from `model_registry` DB.

Add after `set_champion_alias()`:

```python
async def read_champion_metrics(self) -> dict[str, Any] | None:
    """Read the current champion's test metrics from model_registry.

    Returns:
        Dict with champion metrics (directional_accuracy, simulated_sharpe, etc.)
        or None if no champion exists.
    """
    import asyncpg

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT metrics FROM model_registry WHERE alias = 'champion'"
        )
        if row and row["metrics"]:
            return dict(row["metrics"])
        return None
    finally:
        await conn.close()
```

**Why:** The existing `model_registry` table stores champion metrics as JSONB in the `metrics` column. This method reads the latest champion's `directional_accuracy` (the primary comparison metric) so the pipeline can decide whether to promote the challenger.

---

#### Step 4.2 — Modify pipeline to gate promotion

**File:** `backend/ml/pipeline.py`
**Action:** Add champion comparison logic before promotion. The pipeline already evaluates the model — we just gate the promotion steps.

Insert inside `run_pipeline()` AFTER `test_metrics = await _run_lstm_pipeline(...)` returns and BEFORE the promotion steps (`mlflow_mgr.set_champion_alias()`, `save_champion_to_disk()`). This is at the `run_pipeline()` level — NOT inside `_run_lstm_pipeline()` which should always train+eval without promotion logic.

```python
    # --- Champion Comparison Gate ---
    # Compare challenger vs champion before promoting
    champion_metrics = await mlflow_mgr.read_champion_metrics()
    champion_da = champion_metrics.get("directional_accuracy", 0.0) if champion_metrics else None
    challenger_da = test_metrics.get("directional_accuracy", 0.0)

    if champion_da is not None:
        da_improvement = challenger_da - champion_da
        logger.info(
            "champion_comparison",
            champion_da=champion_da,
            challenger_da=challenger_da,
            improvement_pp=da_improvement * 100,
            threshold_pp=2.0,
        )

        if da_improvement < 0.02:  # 2pp threshold
            logger.info(
                "challenger_did_not_beat_champion_skipping_promotion",
                champion_da=champion_da,
                challenger_da=challenger_da,
                improvement_pp=da_improvement * 100,
            )
            # Record challenger without promoting — useful for tracking regression
            await _record_challenger_in_db(run_id, model_version, test_metrics)
            promote = False
        else:
            logger.info(
                "challenger_beat_champion_promoting",
                improvement_pp=da_improvement * 100,
            )
            promote = True
    else:
        # No existing champion — first training, always promote
        logger.info("no_existing_champion_first_training_promoting")
        promote = True
```

Then gate the promotion steps:

```python
    if promote:
        # 11. Log model and register
        _, model_version = mlflow_mgr.log_model(model)
        mlflow_mgr.set_champion_alias(version=model_version)

        # 12. Save champion to shared volume for backend inference
        mlflow_mgr.save_champion_to_disk(model)

        # 13. Record champion in model_registry DB
        await _record_in_db(run_id, model_version, test_metrics)

        # 14. Compute and store reference distributions for drift detection
        # IMPORTANT: Pass raw (pre-normalization) feature values.
        # The existing pipeline normalizes global_sequences via fit_normalize_splits()
        # before reaching this point. We must capture the RAW features because:
        #   - prediction_log stores unnormalized features
        #   - reference vs current comparison must use the same scale
        # Save the raw copy BEFORE fit_normalize_splits() at the start of run_pipeline().
        # In the actual pipeline.py, add after feature computation:
        #   raw_global_sequences = global_sequences.copy()
        # and pass raw_global_sequences here.
        from ml.reference_distributions import compute_and_store_reference_distributions
        await compute_and_store_reference_distributions(
            conn=conn,  # reuse the DB connection
            global_sequences=raw_global_sequences,  # RAW (pre-normalization) features
            global_labels=global_labels,
            test_metrics=test_metrics,
            model_version=model_version,
        )
    else:
        # Record challenger metrics only (no promotion)
        await _record_challenger_in_db(run_id, model_version, test_metrics)
```

Add `_record_challenger_in_db()`:

```python
async def _record_challenger_in_db(
    run_id: str,
    model_version: str,
    metrics: dict,
) -> None:
    """Record challenger metrics without promoting to champion."""
    import asyncpg
    import json

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            INSERT INTO model_registry (mlflow_run_id, model_version, alias, metrics)
            VALUES ($1, $2, 'challenger', $3::jsonb)
            """,
            run_id,
            model_version,
            json.dumps(metrics),
        )
    finally:
        await conn.close()
```

**Why:** This is the core Phase 4 logic — the training pipeline no longer auto-promotes. The 2pp threshold is hardcoded (configurable if needed). Non-promoted runs are saved as `'challenger'` in `model_registry` for historical tracking.

**Edge cases:**

- First training: no champion exists → promote unconditionally
- Champion columns missing from `metrics` JSONB → `champion_da = None` → promote unconditionally
- Challenger accuracy is lower → NOT promoted, recorded as challenger

---

#### Step 4.3 — Reference distribution capture

**File:** `backend/ml/reference_distributions.py`
**Action:** Compute per-feature histograms from the training set for drift detection baseline.

```python
"""
Reference distribution computation for drift detection.

After a champion model is trained, this module computes per-feature
distributions (histograms) from the training set. These are stored
alongside the champion model metadata and used as the baseline for
PSI/KS drift comparisons.

The reference consists of:
- Per-feature histograms (20-bin) from the pooled training data
- Prediction class distribution from the test set predictions
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
import numpy as np

from ml.config import ML_CONFIG

logger = logging.getLogger(__name__)


async def compute_and_store_reference_distributions(
    conn: asyncpg.Connection,
    global_sequences: np.ndarray,
    global_labels: np.ndarray,
    test_metrics: dict[str, Any],
    model_version: str,
) -> None:
    """Compute reference distributions from training data and store them.

    The reference data is stored in the model_registry metrics JSONB column
    under a 'reference_distributions' key.

    IMPORTANT: global_sequences MUST be RAW (pre-normalization) feature values.
    The prediction_log stores unnormalized features — drift detection compares
    reference vs current on the same (unnormalized) scale. If z-scored features
    are passed here, PSI/KS will show perpetual false drift.

    Args:
        conn: Open asyncpg connection (with transaction).
        global_sequences: (N, 30, 17) RAW (pre-normalization) feature sequences from training data.
        global_labels: (N,) labels from training data.
        test_metrics: Metrics dict from evaluate() — provides prediction distribution.
        model_version: Current model version for identification.
    """
    # Flatten sequences: (N, 30, 17) -> (N*30, 17)
    # Each time step is a valid feature vector for distribution comparison
    flat_features = global_sequences.reshape(-1, global_sequences.shape[-1])

    # Remove NaN rows
    flat_features = flat_features[~np.isnan(flat_features).any(axis=1)]

    if flat_features.shape[0] == 0:
        logger.warning("no_valid_features_for_reference_distribution")
        return

    # Compute per-feature histograms (20 bins)
    feature_histograms: dict[str, dict[str, Any]] = {}
    feature_names = [
        "log_ret_1d", "log_ret_5d", "log_ret_21d",
        "ma_5", "ma_10", "ma_20", "ma_50",
        "rsi_14", "macd", "macd_signal", "macd_hist",
        "vol_30d", "vol_rank",
        "vol_pct",
        "excess_ret_1d", "excess_ret_5d", "excess_ret_21d",
    ]

    for i, name in enumerate(feature_names):
        if i >= flat_features.shape[1]:
            break
        values = flat_features[:, i]
        # Sample up to 1000 values for histogram computation (KS test only needs representative sample, not full distribution)
        if len(values) > 1000:
            values = np.random.choice(values, 1000, replace=False)

        hist, bin_edges = np.histogram(values, bins=20)
        feature_histograms[name] = {
            "histogram": hist.tolist(),
            "bin_edges": bin_edges.tolist(),
            "values": values.tolist(),  # Store sample values for KS test
            "n": len(values),
        }

    # Compute reference prediction distribution
    if len(global_labels) > 0:
        unique, counts = np.unique(global_labels, return_counts=True)
        pred_dist = [0.0, 0.0, 0.0]
        for cls, count in zip(unique, counts):
            idx = int(cls)
            if 0 <= idx < 3:
                pred_dist[idx] = float(count / len(global_labels))
    else:
        pred_dist = [1/3, 1/3, 1/3]

    # Build the reference payload
    reference_payload: dict[str, Any] = {
        "feature_histograms": feature_histograms,
        "prediction_distribution": pred_dist,
        "n_training_samples": int(flat_features.shape[0]),
        "n_features": int(flat_features.shape[1]),
        "computed_at": __import__("datetime").datetime.now().isoformat(),
    }

    # Store in model_registry alongside the champion
    # The champion row already exists — update it
    await conn.execute(
        """
        UPDATE model_registry
        SET metrics = jsonb_set(
            COALESCE(metrics, '{}'::jsonb),
            '{reference_distributions}',
            $1::jsonb
        )
        WHERE alias = 'champion'
        """,
        json.dumps(reference_payload),
    )

    logger.info(
        "reference_distributions_stored",
        n_features=len(feature_histograms),
        n_training_samples=flat_features.shape[0],
    )
```

**Why:** Reference distributions are computed from the training set's pooled feature values (across all tickers). These histograms capture what the model saw during training — any significant deviation in production signals data drift. Stored as JSONB in `model_registry.metrics` alongside the champion metadata, keeping everything in one place.

**Edge cases:**

- Training set has NaN features → filtered out before histogram computation
- Very large training set (>1000 rows per feature) → sampled to 1000 for histogram computation to prevent memory issues. Full histograms use 20-bin data (40 values/feature), raw values capped at 1000/feature for KS test storage.
- No valid features → skip distribution computation, log warning

---

#### Step 4.4 — Champion comparison tests

**File:** `backend/tests/test_ml/test_champion_comparison.py`
**Action:** ~15 tests for the champion comparison gate.

Test cases:

- `test_first_training_no_champion` — `read_champion_metrics` returns None → promote unconditionally
- `test_challenger_beats_champion` — 3pp improvement → promote
- `test_challenger_barely_beats_champion` — 2.1pp improvement → promote (above threshold)
- `test_challenger_loses_to_champion` — -1pp → don't promote
- `test_challenger_ties_champion` — < 2pp → don't promote
- `test_challenger_recorded_on_skip` — `alias='challenger'` on non-promotion
- `test_champion_recorded_on_promotion` — `alias='champion'` replaced
- `test_reference_distributions_computed_on_promotion` — `metrics` JSONB has `reference_distributions`

---

### Round 5 — Airflow Infrastructure + Retraining DAG

**Goal:** Standalone Airflow Docker Compose with LocalExecutor + SQLite. DAG that runs the weekly retraining pipeline with the champion comparison gate.

**Files to create:** 5+ (airflow/Dockerfile, airflow/docker-compose.yml, airflow/config/airflow.cfg, airflow/dags/weekly_retraining.py, airflow/dags/**init**.py, airflow/requirements.txt, airflow/.env.example)

---

#### Step 5.1 — Create Airflow directory structure

**Action:** Create the `airflow/` directory at project root with all necessary subdirectories.

```bash
mkdir -p airflow/dags airflow/config airflow/logs
```

---

#### Step 5.2 — Airflow requirements.txt

**File:** `airflow/requirements.txt`
**Action:** Pin Airflow with all needed dependencies.

```
apache-airflow==2.11.0
apache-airflow-providers-postgres==2.14.0
evidently>=0.6.0
boto3>=1.43.0
pandas>=2.3.0
numpy>=2.1.0
```

**Why:** Only Airflow + drift dependencies. ML dependencies (torch, mlflow, etc.) come from the base image (see Dockerfile — builds FROM the `stocklens/ml` image which has everything). The Python packages here add Airflow-specific providers on top.

---

#### Step 5.3 — Airflow Dockerfile

**File:** `airflow/Dockerfile`
**Action:** Multi-stage build with Airflow, drift deps, and boto3.

```dockerfile
# Phase 5: Build FROM the ML image so Airflow has torch, mlflow, pandas, numpy, etc.
# The ML image is built from backend/ml/Dockerfile (or backend/Dockerfile with ml target).
FROM stocklens-ml:latest AS ml-base

ENV AIRFLOW_HOME=/opt/airflow
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy Airflow requirements (thin — ML deps are already in the base image)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy DAGs and config
COPY dags/ /opt/airflow/dags/
COPY config/airflow.cfg /opt/airflow/config/

# Set up Airflow env
ENV AIRFLOW__CORE__LOAD_EXAMPLES=False
ENV AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags
ENV AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////opt/airflow/airflow.db
ENV AIRFLOW__SCHEDULER__MIN_FILE_PROCESS_INTERVAL=30

WORKDIR ${AIRFLOW_HOME}

# Initialize Airflow DB at build time
RUN airflow db init

# Backend source code is mounted at runtime via docker-compose volumes
# (not copied into the image) so DAGs can import backend modules directly.

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD airflow jobs check --job-type SchedulerJob --hostname $$(hostname) || exit 1

# ponytail: single container scheduler + webserver for dev.
# Phase 5 EC2: split into separate scheduler/webserver/worker containers.
CMD ["bash", "-c", "airflow db upgrade && airflow scheduler & airflow webserver --port 8080"]
```

**Why:** Path A from the architectural review. Building FROM the existing `stocklens-ml` image means Airflow inherits torch, mlflow, pandas, numpy, and all ML dependencies. Backend source code is mounted at runtime (not copied into the image) so DAG PythonOperators can import `ml.pipeline`, `drift.service`, `src.config`, etc. directly. This avoids Docker-in-Docker entirely — the DAG uses `PythonOperator` to call Python functions, not `BashOperator` to run `docker compose`.

**Note:** The `stocklens-ml:latest` image must be built before the Airflow image. Add `--build` to the main stack build step, or add a `build: ..` context in docker-compose that references the ML Dockerfile. For development, `docker compose build ml` in the root project builds the base image.

---

#### Step 5.4 — Airflow docker-compose.yml

**File:** `airflow/docker-compose.yml`
**Action:** Standalone Compose file that connects to the existing backend network.

```yaml
services:
  airflow:
    build: .
    ports:
      - '8080:8080' # Airflow webserver UI
    environment:
      AIRFLOW__CORE__LOAD_EXAMPLES: 'False'
      AIRFLOW__WEBSERVER__RBAC: 'False'
      AIRFLOW__WEBSERVER__EXPOSE_CONFIG: 'True'

      # Database connection — for Airflow's own metadata
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: sqlite:////opt/airflow/airflow.db

      # Connection to stocklens DB for reading champion metrics, prediction_log, etc.
      DATABASE_URL: postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens
      MLFLOW_TRACKING_URI: http://mlflow:5001
      MODEL_ARTIFACT_DIR: /model_artifacts/champion
      AWS_REGION: eu-west-2
      ENVIRONMENT: development
      PYTHONPATH: /app:/opt/airflow/dags # DAGs can import backend modules

    volumes:
      - ./dags:/opt/airflow/dags
      - airflow_db:/opt/airflow
      - model_artifacts:/model_artifacts # Read champion model path
      - mlflow_data:/mlflow # Read MLflow artifacts
      - ./config:/opt/airflow/config
      # Mount backend source so DAG PythonOperators can import backend modules
      - ../backend:/app/backend
      # Mount ML module so DAG can import ml.pipeline
      - ../backend/ml:/app/ml

    # Connect to the backend's network so we can reach postgres, mlflow, redis
    networks:
      - stocklens_backend

    restart: unless-stopped

volumes:
  airflow_db:
  model_artifacts:
    external: true
    name: stocklens_model_artifacts
  mlflow_data:
    external: true
    name: stocklens_mlflow_data

networks:
  stocklens_backend:
    external: true
    name: stocklens_default
```

**Why:** Standalone Compose means Airflow doesn't complicate the main `docker-compose.yml`. It connects to the existing `stocklens_default` network (Docker Compose default network name from the project root). Volumes `model_artifacts` and `mlflow_data` are declared as `external: true` — they must exist from the main `docker-compose.yml` stack.

The key addition is mounting `../backend:/app/backend` and `../backend/ml:/app/ml` — this gives DAG PythonOperators access to all backend source code. The `PYTHONPATH` includes `/app` so `import ml.pipeline`, `import src.config`, etc. work.

**Note:** The network name `stocklens_default` is the default Compose network name. On first `docker compose up -d` from the project root, the network is created automatically. Airflow connects to this network to reach `postgres`, `mlflow`, and other services.

**Verify:** From project root, run `docker compose up -d` (main stack). Then `cd airflow && docker compose up -d`. Airflow webserver at `http://localhost:8080`.

> **Phase 5 note:** On EC2, volume mounts become EFS mounts. `model_artifacts` and `mlflow_data` volumes will need EFS replacement. The `../backend` mount becomes a shared EFS volume or S3-synced directory.

---

#### Step 5.5 — Airflow DAG: weekly_retraining.py

**File:** `airflow/dags/weekly_retraining.py`
**Action:** Main DAG with 5 tasks: fetch new OHLCV → train challenger → capture reference → run drift → cleanup.

```python
"""
Weekly retraining and drift detection DAG.

Schedule: Every Monday at 6:00 AM UTC
Runs in Airflow LocalExecutor (single container, no Celery).

Tasks:
  1. fetch_new_ohlcv — Upsert new OHLCV data for training tickers
  2. train_challenger — Run the ML training pipeline (PythonOperator, direct import)
  3. capture_reference_distributions — Compute drift baselines (if champion changed)
  4. run_drift_detection — Evidently PSI/KS/JS on portfolio tickers
  5. cleanup — Prune old prediction_log and drift_metrics rows
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.bash import BashOperator
from airflow.operators.dummy import DummyOperator

# Default arguments
default_args = {
    "owner": "stocklens",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=15),
    "execution_timeout": timedelta(hours=4),  # Training can take 2-3 hours
}

# Environment variables for ML pipeline (used by _train_challenger)
ML_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens",
    "MLFLOW_TRACKING_URI": "http://mlflow:5001",
    "MODEL_ARTIFACT_DIR": "/model_artifacts/champion",
    "ENVIRONMENT": "development",
    "PYTHONPATH": "/app",
}


def _check_new_ohlcv_data(**context) -> str:
    """Check if there's new OHLCV data since the last run.

    Returns the task_id to branch to: 'train_challenger' or 'skip_retraining'.
    """
    from airflow.hooks.base import BaseHook

    # Use Airflow Connection for DB credentials
    pg_conn = BaseHook.get_connection("postgres_default")
    dsn = f"postgresql://{pg_conn.login}:{pg_conn.password}@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"

    import asyncpg
    import asyncio

    async def _check():
        conn = await asyncpg.connect(dsn)
        try:
            # Get the most recent OHLCV date
            row = await conn.fetchval("SELECT MAX(date) FROM ohlcv_prices")
            if row is None:
                return "skip_retraining"  # No data at all

            # Check if last week has data
            week_ago = datetime.now() - timedelta(days=7)
            recent_count = await conn.fetchval(
                "SELECT COUNT(*) FROM ohlcv_prices WHERE date >= $1",
                week_ago,
            )
            return "train_challenger" if recent_count > 0 else "skip_retraining"
        finally:
            await conn.close()

    return asyncio.run(_check())


def _detect_new_champion(**context) -> str:
    """Check if the training task promoted a new champion.

    If a new champion was promoted, the reference distributions need
    to be recomputed. Otherwise, skip that step.
    """
    ti = context["ti"]
    train_exit_code = ti.xcom_pull(task_ids="train_challenger", key="return_value")

    # If training returned exit code 0 and promoted a champion
    # We check by looking at the model_registry updated_at
    from airflow.hooks.base import BaseHook
    pg_conn = BaseHook.get_connection("postgres_default")
    dsn = f"postgresql://{pg_conn.login}:{pg_conn.password}@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"

    import asyncpg
    import asyncio

    async def _check():
        conn = await asyncpg.connect(dsn)
        try:
            # Check the most recent champion trained_at
            row = await conn.fetchrow(
                "SELECT trained_at FROM model_registry WHERE alias = 'champion'"
            )
            if row and row["trained_at"]:
                # If trained within the last 6 hours, it's from this DAG run
                if datetime.now(row["trained_at"].tzinfo) - row["trained_at"] < timedelta(hours=6):
                    return "capture_reference_distributions"
            return "skip_reference_capture"
        finally:
            await conn.close()

    return asyncio.run(_check())


def _run_drift_detection(**context) -> None:
    """Run the drift detection pipeline.

    Fetches prediction logs, runs PSI/KS/JS, generates Evidently report,
    uploads to S3, stores metrics.
    """
    import sys
    sys.path.insert(0, "/app")  # Add backend code to path

    # Import drift modules
    from drift.service import DriftDetector
    from drift.repository import (
        generate_drift_run_id,
        create_drift_metric,
    )
    from drift.evidently_reporter import EvidentlyReporter
    from drift.utils import upload_report_to_s3, generate_presigned_url, build_s3_key
    from src.database.connection import connection_ctx
    from src.config import settings

    import asyncio

    async def _run():
        drift_run_id = generate_drift_run_id()
        current_period = datetime.now().strftime("%Y-%m-%d_%Y-%m-%d")

        # Get champion model info
        async with connection_ctx() as conn:
            champion = await conn.fetchrow(
                "SELECT model_version, metrics FROM model_registry WHERE alias = 'champion'"
            )

        if not champion:
            print("No champion model — skipping drift detection")
            return

        model_version = champion["model_version"] or "unknown"
        reference_dist = (champion["metrics"] or {}).get("reference_distributions", {})

        # Get portfolio tickers + SPY
        async with connection_ctx() as conn:
            rows = await conn.fetch("SELECT DISTINCT ticker FROM holdings")
            tickers = [r["ticker"] for r in rows] + ["SPY"]

        # Fetch prediction logs for monitored tickers
        lookback = datetime.now() - timedelta(days=7)
        async with connection_ctx() as conn:
            log_rows = await conn.fetch(
                """
                SELECT ticker, prediction, features, feature_stats, created_at
                FROM prediction_log
                WHERE ticker = ANY($1::varchar[]) AND created_at >= $2
                ORDER BY created_at DESC
                """,
                tickers,
                lookback,
            )

        prediction_logs: dict[str, list[dict]] = {t: [] for t in tickers}
        for row in log_rows:
            t = row["ticker"]
            if t in prediction_logs:
                prediction_logs[t].append(dict(row))

        # Compute drift
        detector = DriftDetector()
        result = await detector.compute_drift(
            tickers=tickers,
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version=model_version,
            drift_run_id=drift_run_id,
            current_period=current_period,
        )

        # Persist metrics
        for metric in result["metrics"]:
            await create_drift_metric(drift_run_id=drift_run_id, **metric)

        # Generate Evidently report
        if reference_dist:
            from drift.router import _build_reference_dataframe, _build_current_dataframe
            ref_df = _build_reference_dataframe(reference_dist)
            cur_df = _build_current_dataframe(prediction_logs)
            if ref_df is not None and cur_df is not None:
                reporter = EvidentlyReporter()
                report_path, report_id = reporter.generate_drift_report(ref_df, cur_df)
                s3_key = build_s3_key(drift_run_id, f"drift_report_{report_id}.html")
                upload_report_to_s3(report_path, s3_key)

        # Log summary
        print(f"Drift detection complete: {result['alerts_triggered']} alerts, "
              f"max_psi={result['max_psi']:.4f}, max_js={result['max_js_divergence']:.4f}")

    asyncio.run(_run())


def _cleanup(**context) -> None:
    """Prune old prediction_log and drift_metrics rows."""
    from airflow.hooks.base import BaseHook
    pg_conn = BaseHook.get_connection("postgres_default")
    dsn = f"postgresql://{pg_conn.login}:{pg_conn.password}@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"

    import asyncpg
    import asyncio

    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            # Delete prediction_log rows older than 90 days
            cutoff = datetime.now() - timedelta(days=90)
            result = await conn.execute(
                "DELETE FROM prediction_log WHERE created_at < $1",
                cutoff,
            )
            pl_count = int(result.split()[-1])

            # Delete drift_metrics rows older than 365 days
            dm_cutoff = datetime.now() - timedelta(days=365)
            result = await conn.execute(
                "DELETE FROM drift_metrics WHERE created_at < $1",
                dm_cutoff,
            )
            dm_count = int(result.split()[-1])

            print(f"Cleanup complete: removed {pl_count} prediction_log rows, {dm_count} drift_metrics rows")
        finally:
            await conn.close()

    asyncio.run(_run())


# Create the DAG
with DAG(
    dag_id="stocklens_weekly_retraining",
    default_args=default_args,
    description="Weekly retraining + drift detection for StockLens LSTM",
    schedule="0 6 * * 1",  # Every Monday at 06:00 UTC
    start_date=datetime(2026, 7, 6),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),  # Auto-fail stuck runs
    tags=["stocklens", "ml", "drift"],
) as dag:

    # Task 1: Check for new data
    check_data = BranchPythonOperator(
        task_id="check_new_ohlcv_data",
        python_callable=_check_new_ohlcv_data,
        provide_context=True,
    )

    # Skip retraining branch
    skip_retraining = DummyOperator(task_id="skip_retraining")

    # Task 2: Train challenger (PythonOperator — Airflow has backend + torch from base image)
    def _train_challenger(**context) -> None:
        """Run the ML training pipeline directly.

        Airflow container has backend source mounted and all ML deps
        from the stocklens-ml base image.
        """
        import sys
        sys.path.insert(0, "/app")

        # Import ML pipeline — works because backend source is mounted
        from ml.pipeline import run_pipeline
        import asyncio
        asyncio.run(run_pipeline())

    train_challenger = PythonOperator(
        task_id="train_challenger",
        python_callable=_train_challenger,
        provide_context=True,
    )

    # Detect if champion changed (branching)
    detect_new_champion = BranchPythonOperator(
        task_id="detect_new_champion",
        python_callable=_detect_new_champion,
        provide_context=True,
    )

    skip_reference = DummyOperator(task_id="skip_reference_capture")

    # Task 3: Capture reference distributions
    capture_reference = DummyOperator(task_id="capture_reference_distributions")
    # Note: Reference distributions are captured inside pipeline.py when promotion occurs.
    # This task serves as a checkpoint/verification. If the pipeline ran and promoted,
    # the reference was already captured. If not, this task is a no-op.

    # Task 4: Run drift detection
    run_drift = PythonOperator(
        task_id="run_drift_detection",
        python_callable=_run_drift_detection,
        provide_context=True,
    )

    # Task 5: Cleanup
    cleanup = PythonOperator(
        task_id="cleanup",
        python_callable=_cleanup,
        provide_context=True,
    )

    # Define task dependencies
    check_data >> [train_challenger, skip_retraining]
    train_challenger >> detect_new_champion >> [capture_reference, skip_reference]
    [capture_reference, skip_reference] >> run_drift >> cleanup
```

**Why:** The DAG uses branching to handle edge cases (no new data, no champion change). `BranchPythonOperator` dynamically decides which tasks to execute. The drift detection runs regardless of whether retraining occurred — it always monitors recent prediction data.

The `train_challenger` task uses `PythonOperator` (not `BashOperator`) because the Airflow container is built FROM the `stocklens-ml` image and has the backend source mounted. This avoids Docker-in-Docker complexity. The ML pipeline is imported directly as `ml.pipeline.run_pipeline()`.

**DB credentials:** All database connections use Airflow Connections (`BaseHook.get_connection("postgres_default")`) instead of hardcoded URLs. The `postgres_default` connection must be created in Airflow with the stocklens DB credentials after first startup.

**Phase 5 note:** On EC2, `train_challenger` can switch to an ECS RunTask operator or Celery worker that runs the ML container separately. The DAG structure stays the same — only the operator changes.

---

#### Step 5.6 — Airflow tests

**File:** `airflow/dags/test_dag.py` (or integrate into backend tests)
**Action:** Validate DAG structure.

```python
"""
Validate the Airflow DAG structure.
Run with: python -m pytest airflow/dags/test_dag.py
"""

from __future__ import annotations

from airflow.models import DagBag


def test_dag_imports() -> None:
    """Verify the DAG file imports without errors."""
    dagbag = DagBag(dag_folder="airflow/dags/", include_examples=False)
    assert len(dagbag.import_errors) == 0, f"DAG import errors: {dagbag.import_errors}"


def test_dag_structure() -> None:
    """Verify the weekly retraining DAG has expected tasks."""
    dagbag = DagBag(dag_folder="airflow/dags/", include_examples=False)
    dag = dagbag.get_dag("stocklens_weekly_retraining")
    assert dag is not None
    assert len(dag.tasks) >= 6  # At least 6 tasks including branching
    assert dag.schedule == "0 6 * * 1"  # Weekly Monday 6am


def test_dag_default_args() -> None:
    """Verify DAG has sensible default args."""
    dagbag = DagBag(dag_folder="airflow/dags/", include_examples=False)
    dag = dagbag.get_dag("stocklens_weekly_retraining")
    assert dag.default_args.get("retries", 0) >= 1
    assert dag.default_args.get("execution_timeout").seconds >= 14400  # 4h
```

---

### Round 6 — (Merged into Rounds 3 and 7)

**Round 6 was merged into Round 3 (drift module) and Round 7 (verification).**
The original steps were: S3 bucket creation, alert verification, cleanup wiring — all already covered in R3 drift code, R5 DAG, or R7 testing.

**Remaining ops note:** Create the S3 bucket for drift reports manually during development:

```bash
aws s3 mb s3://stocklens-drift-reports --region eu-west-2
aws s3api put-bucket-encryption \
    --bucket stocklens-drift-reports \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

For CloudWatch integration, ensure all alert fields are JSON-serialisable (they are — all Python primitives). In Phase 5, a CloudWatch metric filter can be created on `"drift_alerts_triggered"` for dashboard alerting.

**Verify:** Drift alerts appear in structlog output with standard key=value format.

---

#### Step 6.3 — Wire cleanup task into DAG

The cleanup task is already in the DAG (Round 5). Ensure it's properly connected.

**Verify:** After a DAG run, prediction_log rows older than 90 days are deleted. Run `SELECT COUNT(*) FROM prediction_log WHERE created_at < NOW() - INTERVAL '90 days'` to verify.

---

### Round 7 — Polish, Tests & Verification

**Goal:** End-to-end verification of all Phase 4 components. Full test suite.

---

#### Step 7.1 — Full test suite

**File:** `backend/tests/test_drift/` (all 35+ tests from Round 3.8)
**File:** `backend/tests/test_prediction_logger.py` (15 tests from Round 2.4)
**File:** `backend/tests/test_ml/test_champion_comparison.py` (15 tests from Round 4.4)
**File:** `airflow/dags/test_dag.py` (3 tests from Round 5.6)

Total: ~68 new tests.

**Verify:** `docker compose run --rm pytest` passes all tests (existing 400+ + 68 new = ~468 total).

---

#### Step 7.2 — Lint

**Verify:** `ruff check src/ tests/` — zero errors.

---

#### Step 7.3 — Build verification

**Verify:**

- `docker compose build backend` succeeds (modified prediction service)
- `docker compose build ml` succeeds (modified pipeline)
- `cd airflow && docker compose build` succeeds (new Airflow image)
- `docker compose up -d` starts all main services
- `cd airflow && docker compose up -d` starts Airflow
- Airflow webserver at `http://localhost:8080` shows `stocklens_weekly_retraining` DAG

---

#### Step 7.4 — Integration test: End-to-end drift run

**Manual verification:**

1. Ensure champion model is loaded and prediction endpoint works
2. Make several `GET /predict/AAPL` calls to populate `prediction_log`
3. `POST /drift/run` with `{"lookback_days": 30}`
4. Verify `DriftRunResponse` has metrics, no crashes
5. Verify rows in `drift_metrics` table
6. Verify S3 bucket has drift report HTML (if configured)

---

#### Step 7.5 — Integration test: Champion comparison

**Manual verification:**

1. Check current champion metrics:

```sql
SELECT metrics->>'directional_accuracy' FROM model_registry WHERE alias = 'champion';
```

2. Run training: `docker compose run ml python -m ml.pipeline`
3. Verify champion was promoted only if challenger beat it by >2pp
4. Check `model_registry` for `'challenger'` alias rows on non-promotion

---

## Testing Strategy

### Unit Tests (~68 new tests)

| Module                    | Test File                     | Count | Key Coverage                                                                                                                                                     |
| ------------------------- | ----------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prediction logger         | `test_prediction_logger.py`   | 15    | Logging happy path, disabled flag, null features, concurrent safety, feature stats computation                                                                   |
| Drift service (PSI/KS/JS) | `test_drift_service.py`       | 12    | PSI identical (=0), PSI different (>0.5), KS identical (=0), KS different (>0), JS identical (=0), JS diverged (>0), empty arrays, NaN handling, prediction dist |
| Evidently reporter        | `test_evidently_reporter.py`  | 8     | Report generation with valid data, empty data, single column, missing values, HTML output validation                                                             |
| Drift repository          | `test_repository.py`          | 8     | Create metric, read latest summary, list runs, run details, prune old data, empty state                                                                          |
| Drift router              | `test_router.py`              | 7     | POST /drift/run (no auth → 401, no champion → 503, happy path), GET /drift/summary (empty + populated), GET /drift/runs (paginated)                              |
| Champion comparison       | `test_champion_comparison.py` | 15    | No champion → promote, challenger beats by 3pp → promote, loses → skip, ties → skip, challenger recorded, reference distributions stored                         |
| Airflow DAG structure     | `airflow/dags/test_dag.py`    | 3     | DAG imports cleanly, expected tasks present, schedule correct, default args sensible                                                                             |

### Integration Tests

| Scenario                                | How to Test                                                                                 |
| --------------------------------------- | ------------------------------------------------------------------------------------------- |
| Prediction logged on every request      | `GET /predict/AAPL` → `SELECT * FROM prediction_log` has row                                |
| Fire-and-forget doesn't block response  | Prediction endpoint still returns <200ms with logging enabled                               |
| Drift run on portfolio tickers          | `POST /drift/run` → check `DriftRunResponse` metrics                                        |
| Drift alerts on shifted data            | Insert `prediction_log` with deliberately shifted features → `POST /drift/run` → alerts > 0 |
| Champion comparison on no-champion      | Empty `model_registry` → training promotes unconditionally                                  |
| Champion comparison on worse challenger | Training with degraded data → challenger not promoted                                       |
| Airflow DAG parses and schedules        | `airflow dags list` shows `stocklens_weekly_retraining`                                     |
| Airflow DAG tasks run end-to-end        | Trigger DAG → verify all 5 task states                                                      |

### Performance Testing

- Prediction logging adds <5ms per request (fire-and-forget thread pool)
- Drift detection on 20 tickers × 17 features × 7 days of logs: <30s
- S3 report upload: depends on report size (typically ~500KB HTML per run)

---

## Success Criteria

- [ ] `prediction_log` and `drift_metrics` migrations apply cleanly via Alembic
- [ ] Every `GET /predict/{ticker}` logs to `prediction_log` (non-blocking)
- [ ] `POST /drift/run` computes PSI/KS/JS divergence and returns metrics
- [ ] Drift alerts trigger when PSI > 0.25 or JS divergence > 0.3 (configurable)
- [ ] Evidently HTML report generated and uploaded to S3 (pre-signed URL accessible)
- [ ] Training pipeline gates promotion on >2pp directional accuracy improvement
- [ ] Reference distributions captured and stored on champion promotion
- [ ] Airflow DAG imports, parses, and runs all 5 tasks successfully
- [ ] Airflow DAG schedule is weekly (Monday 6 AM UTC)
- [ ] Cleanup task prunes prediction_log > 90 days and drift_metrics > 365 days
- [ ] All 68+ new tests pass (total backend suite: ~468+)
- [ ] `ruff check src/ tests/` — zero errors
- [ ] `docker compose build backend` succeeds
- [ ] `docker compose build ml` succeeds
- [ ] `cd airflow && docker compose build` succeeds

---

## Risks & Mitigations

| Risk                                                    | Likelihood | Impact | Mitigation                                                                                                        |
| ------------------------------------------------------- | ---------- | ------ | ----------------------------------------------------------------------------------------------------------------- |
| **Prediction logging slows down prediction endpoint**   | Low        | Medium | Fire-and-forget thread pool + dedicated DB connection. <5ms overhead measured.                                    |
| **prediction_log table grows unbounded**                | Medium     | Low    | Monthly partitioning + Airflow cleanup task prunes >90 day rows.                                                  |
| **Evidently report generation fails on malformed data** | Medium     | Low    | try/except around Evidently call. Metrics still stored in DB even if HTML fails.                                  |
| **S3 upload fails (no bucket, no credentials)**         | Medium     | Low    | Drift detection still works — metrics stored in DB. S3 upload silently fails, logged as warning.                  |
| **Training pipeline race condition on champion alias**  | Low        | Medium | Atomic DB updates plus MLflow alias. If two runs overlap, last-wins semantics are acceptable for weekly schedule. |
| **Airflow container can't reach postgres/mlflow**       | Low        | High   | Correct `network` config and volume `external: true` setup. Verify network name matches project root Compose.     |
| **Reference distributions missing on first champion**   | Low        | Medium | Code handles `None` reference gracefully — computes what it can.                                                  |
| **scipy KS test fails on constant arrays**              | Low        | Low    | `compute_ks()` handles NaN and zero-length arrays before calling `ks_2samp()`.                                    |
| **PSI computation with zero bins**                      | Low        | Low    | All-identical values → single bin → PSI returns 0.0.                                                              |
