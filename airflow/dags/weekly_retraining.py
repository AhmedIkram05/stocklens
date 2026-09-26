"""
StockLens weekly retraining + drift detection DAG.

Schedule: Every Monday at 06:00 UTC
Runs via Airflow LocalExecutor (single container, SQLite metadata).

The DAG owns its data lifecycle: it ingests fresh OHLCV before deciding
whether to retrain, so the training window always ends near today.

Tasks:
  1. ingest_training_universe — Append fresh daily bars for every training
     ticker (+SPY) from Yahoo v8 (idempotent, ON CONFLICT DO NOTHING)
  2. check_new_ohlcv_data     — Branch: retrain only if the newest price date
     advanced >= 14 days past the champion's trained_at (staleness guard)
  3. train_challenger         — Run the ML training pipeline via ECS GPU task (EcsRunTaskOperator)
  4. detect_new_champion      — If champion was promoted, recompute reference distributions
  5. run_drift_detection      — PSI/KS/JS on portfolio tickers, Evidently report, S3 upload
  6. cleanup                  — Prune old prediction_log (>90d) and drift_metrics (>365d)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from airflow.models import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.providers.amazon.aws.operators.ecs import EcsRunTaskOperator

# ── Default arguments ──────────────────────────────────────────────────────────
default_args = {
    "owner": "stocklens",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=15),
    "execution_timeout": timedelta(hours=4),
}

# Retrain only when the price tail advanced at least this far past the
# champion's trained_at. Weekly runs re-ingest (~25 min) but skip training
# unless the universe actually grew two weeks' worth of new labeled windows.
STALENESS_DAYS = 14

# Ingest fetches the training window + buffer so deep-history (Kaggle-backed)
# tickers keep their yfinance tail contiguous with the training cutoff.
INGEST_BUFFER_YEARS = 2


def _pg_conn():
    """The stocklens DB connection from postgres_default."""
    from airflow.hooks.base import BaseHook

    return BaseHook.get_connection("postgres_default")


def _pg_dsn() -> str:
    """Asyncpg DSN for the stocklens DB from the postgres_default connection."""
    pg_conn = _pg_conn()
    return (
        f"postgresql://{pg_conn.login}:{pg_conn.password}"
        f"@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"
    )


# ── Task implementations ───────────────────────────────────────────────────────
def _run_ingest(**context) -> None:
    """Ingest fresh OHLCV for the full training universe (+SPY) via seed script."""
    script = _seed_script_path()
    pg_conn = _pg_conn()
    years = int(v("ml_ohlcv_years") or 10) + INGEST_BUFFER_YEARS

    env = dict(os.environ)
    env["DATABASE_DSN"] = (
        f"host={pg_conn.host} port={pg_conn.port or 5432}"
        f" dbname={pg_conn.schema or 'stocklens'}"
        f" user={pg_conn.login} password={pg_conn.password}"
    )
    env["TRAINING_TICKERS"] = v("training_tickers") or "ALL"

    result = subprocess.run(
        [sys.executable, script, "--years", str(years)],
        env=env,
        capture_output=True,
        text=True,
        timeout=90 * 60,  # ~489 tickers x 2s delay + fetch time + retries headroom
    )
    tail = (result.stdout or "").strip().splitlines()[-3:]
    print(f"Ingest exit={result.returncode}: {tail}")
    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip().splitlines()[-5:]
        raise RuntimeError(
            f"OHLCV ingest failed (exit {result.returncode}). stderr tail: {stderr_tail}"
        )


def _seed_script_path() -> str:
    """Locate backend/scripts/seed_ohlcv.py across dev mount, prod image, and repo checkout."""
    repo_candidate = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "backend", "scripts", "seed_ohlcv.py",
    )
    for candidate in (
        "/app/backend/scripts/seed_ohlcv.py",
        "/app/scripts/seed_ohlcv.py",
        repo_candidate,
    ):
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        "seed_ohlcv.py not found at /app/backend/scripts, /app/scripts, or "
        f"{repo_candidate} — the Airflow image must copy backend/ (Dockerfile: COPY backend/ /app/)"
    )


def _check_new_ohlcv_data(**context) -> str:
    """Branch: train only if data advanced >= STALENESS_DAYS past champion."""
    import asyncpg

    dsn = _pg_dsn()

    async def _check():
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                """
                SELECT (SELECT MAX(date) FROM ohlcv_prices) AS max_date,
                       (SELECT trained_at FROM model_registry
                        WHERE alias = 'champion'
                        ORDER BY trained_at DESC LIMIT 1) AS champion_trained_at
                """
            )
            if row is None or row["max_date"] is None:
                return "skip_retraining"
            # No champion yet — bootstrap training.
            if row["champion_trained_at"] is None:
                return "train_challenger"
            trained_at = row["champion_trained_at"]
            tz = trained_at.tzinfo or timezone.utc
            max_date = datetime(
                row["max_date"].year, row["max_date"].month, row["max_date"].day, tzinfo=tz,
            )
            advance = (max_date - trained_at).days
            print(
                f"Staleness check: newest price date {row['max_date']}, "
                f"champion trained_at {trained_at}, advance {advance}d "
                f"(threshold {STALENESS_DAYS}d)"
            )
            return "train_challenger" if advance >= STALENESS_DAYS else "skip_retraining"
        finally:
            await conn.close()

    return asyncio.run(_check())


# ── Variables helper (env-backed, see init_airflow_variables.sh) ──
def v(key: str) -> str:
    from airflow.sdk import Variable
    return Variable.get(key)


def _detect_new_champion(**context) -> str:
    """Check if training promoted a new champion → recompute ref distributions."""
    import asyncpg

    dsn = _pg_dsn()

    async def _check():
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT trained_at FROM model_registry WHERE alias = 'champion'",
            )
            if row and row["trained_at"]:
                trained_at = row["trained_at"]
                tz = trained_at.tzinfo
                now = datetime.now(tz=tz or timezone.utc)
                if now - trained_at < timedelta(hours=6):
                    return "capture_reference_distributions"
            return "skip_reference_capture"
        finally:
            await conn.close()

    return asyncio.run(_check())


def _run_drift_detection(**context) -> None:
    """Run drift detection: PSI/KS/JS, Evidently report, S3 upload, DB persist."""
    import sys
    sys.path.insert(0, "/app")

    from drift.evidently_reporter import (
        EvidentlyReporter,  # type: ignore[import-untyped]
    )
    from drift.repository import (  # type: ignore[import-untyped]
        create_drift_metric,
        generate_drift_run_id,
    )
    from drift.router import (  # type: ignore[import-untyped]
        _build_current_dataframe,
        _build_reference_dataframe,
    )
    from drift.service import DriftDetector  # type: ignore[import-untyped]
    from drift.utils import (  # type: ignore[import-untyped]
        build_s3_key,
        upload_report_to_s3,
    )
    from src.database.connection import connection_ctx  # type: ignore[import-untyped]

    async def _run():
        drift_run_id = generate_drift_run_id()
        current_period = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%Y-%m-%d")

        # Get champion model
        async with connection_ctx() as conn:
            champion = await conn.fetchrow(
                "SELECT model_version, metrics FROM model_registry WHERE alias = 'champion'",
            )
        if not champion:
            print("No champion model — skipping drift detection")
            return

        model_version = champion["model_version"] or "unknown"
        reference_dist = (champion["metrics"] or {}).get("reference_distributions", {})

        # Portfolio tickers + SPY
        async with connection_ctx() as conn:
            rows = await conn.fetch("SELECT DISTINCT ticker FROM holdings")
            tickers = [r["ticker"] for r in rows] + ["SPY"]

        # Fetch prediction logs (last 7 days)
        lookback = datetime.now(tz=timezone.utc) - timedelta(days=7)
        async with connection_ctx() as conn:
            log_rows = await conn.fetch(
                """SELECT ticker, prediction, features, feature_stats, created_at
                   FROM prediction_log
                   WHERE ticker = ANY($1::varchar[]) AND created_at >= $2
                   ORDER BY created_at DESC""",
                tickers, lookback,
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

        # Generate Evidently report & upload to S3
        if reference_dist:
            ref_df = _build_reference_dataframe(reference_dist)
            cur_df = _build_current_dataframe(prediction_logs)
            if ref_df is not None and cur_df is not None:
                reporter = EvidentlyReporter()
                report_path, report_id = reporter.generate_drift_report(ref_df, cur_df)
                s3_key = build_s3_key(drift_run_id, f"drift_report_{report_id}.html")
                upload_report_to_s3(report_path, s3_key)

        print(
            f"Drift complete: {result['alerts_triggered']} alerts, "
            f"max_psi={result['max_psi']:.4f}, max_js={result['max_js_divergence']:.4f}",
        )

    asyncio.run(_run())


def _cleanup(**context) -> None:
    """Prune old prediction_log and drift_metrics rows."""
    import asyncpg

    dsn = _pg_dsn()

    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            # prediction_log > 90 days
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=90)
            result = await conn.execute(
                "DELETE FROM prediction_log WHERE created_at < $1", cutoff,
            )
            pl_count = int(result.split()[-1])

            # drift_metrics > 365 days
            dm_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=365)
            result = await conn.execute(
                "DELETE FROM drift_metrics WHERE created_at < $1", dm_cutoff,
            )
            dm_count = int(result.split()[-1])

            print(
                f"Cleanup: removed {pl_count} prediction_log rows, "
                f"{dm_count} drift_metrics rows",
            )
        finally:
            await conn.close()

    asyncio.run(_run())


# ── DAG definition ─────────────────────────────────────────────────────────────
with DAG(
    dag_id="stocklens_weekly_retraining",
    default_args=default_args,
    description="Weekly retraining + drift detection for StockLens LSTM",
    schedule="0 6 * * 1",  # Every Monday 06:00 UTC
    start_date=datetime(2026, 7, 6, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),
    tags=["stocklens", "ml", "drift"],
) as dag:

    # ── Task 1: Ingest fresh OHLCV for the training universe (always) ──
    ingest_universe = PythonOperator(
        task_id="ingest_training_universe",
        python_callable=_run_ingest,
    )

    # ── Task 2: Staleness guard (branch) ──
    check_data = BranchPythonOperator(
        task_id="check_new_ohlcv_data",
        python_callable=_check_new_ohlcv_data,
    )

    skip_retraining = EmptyOperator(task_id="skip_retraining")

    # ── Task 3: Train challenger (runs on GPU via ECS EcsRunTaskOperator) ──
    train_challenger = EcsRunTaskOperator(
        task_id="train_challenger",
        cluster=v("ecs_cluster_name"),
        task_definition=v("ml_training_task_definition"),
        launch_type="EC2",
        network_configuration={
            "awsvpcConfiguration": {
                "subnets": v("private_subnet_ids").split(","),
                "securityGroups": [v("airflow_sg_id")],
                "assignPublicIp": "ENABLED",
            },
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "ml-training",
                    "environment": [
                        {"name": "DATABASE_URL", "value": v("database_url")},
                        {"name": "MLFLOW_TRACKING_URI", "value": v("mlflow_tracking_uri")},
                        {"name": "MODEL_ARTIFACT_DIR", "value": "/model_artifacts/champion"},
                        {"name": "MLFLOW_ARTIFACT_ROOT", "value": "/mlflow/artifacts"},
                        {"name": "MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING", "value": "true"},
                        {"name": "ENVIRONMENT", "value": v("environment")},
                        {"name": "AWS_REGION", "value": v("aws_region")},
                        {"name": "CHAMPION_S3_URI", "value": v("champion_s3_uri")},
                        # Winning recipe (must match the locally-validated rebuild)
                        {"name": "TRAINING_TICKERS", "value": v("training_tickers")},
                        {"name": "ML_OHLCV_YEARS", "value": v("ml_ohlcv_years")},
                        {"name": "ML_THRESHOLD_MULT", "value": v("ml_threshold_mult")},
                        {"name": "ML_SEEDS", "value": v("ml_seeds")},
                    ],
                },
            ],
        },
        awslogs_group=f"/ecs/{v('app_name')}-airflow-{v('environment')}",
        awslogs_region=v("aws_region"),
        awslogs_stream_prefix="ecs/ml-training",
        reattach=True,
        waiter_delay=30,
        waiter_max_attempts=360,
        do_xcom_push=True,
    )

    # ── Branch: detect champion change ──
    detect_new_champion = BranchPythonOperator(
        task_id="detect_new_champion",
        python_callable=_detect_new_champion,
    )

    skip_reference = EmptyOperator(task_id="skip_reference_capture")

    # ── Task 3: Capture reference distributions (checkpoint — already done in pipeline) ──
    capture_reference = EmptyOperator(task_id="capture_reference_distributions")

    # ── Task 4: Run drift detection ──
    run_drift = PythonOperator(
        task_id="run_drift_detection",
        python_callable=_run_drift_detection,
    )

    # ── Task 5: Cleanup ──
    cleanup = PythonOperator(
        task_id="cleanup",
        python_callable=_cleanup,
    )

    # ── Task dependencies ──
    ingest_universe >> check_data >> [train_challenger, skip_retraining]
    train_challenger >> detect_new_champion >> [capture_reference, skip_reference]
    [capture_reference, skip_reference] >> run_drift >> cleanup
