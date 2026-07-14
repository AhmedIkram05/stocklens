"""
StockLens weekly retraining + drift detection DAG.

Schedule: Every Monday at 06:00 UTC
Runs via Airflow LocalExecutor (single container, SQLite metadata).

Tasks:
  1. check_new_ohlcv_data — Check if new OHLCV data exists since last run
  2. train_challenger      — Run the ML training pipeline via ECS GPU task (EcsRunTaskOperator)
  3. detect_new_champion   — If champion was promoted, recompute reference distributions
  4. run_drift_detection   — PSI/KS/JS on portfolio tickers, Evidently report, S3 upload
  5. cleanup               — Prune old prediction_log (>90d) and drift_metrics (>365d)
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

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


# ── Task implementations ───────────────────────────────────────────────────────
def _check_new_ohlcv_data(**context) -> str:
    """Check for new OHLCV data since last run. Branch: train or skip."""
    from airflow.hooks.base import BaseHook

    pg_conn = BaseHook.get_connection("postgres_default")
    dsn = (
        f"postgresql://{pg_conn.login}:{pg_conn.password}"
        f"@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"
    )
    import asyncpg

    async def _check():
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchval("SELECT MAX(date) FROM ohlcv_prices")
            if row is None:
                return "skip_retraining"
            week_ago = datetime.now() - timedelta(days=7)
            recent = await conn.fetchval(
                "SELECT COUNT(*) FROM ohlcv_prices WHERE date >= $1", week_ago,
            )
            return "train_challenger" if recent and recent > 0 else "skip_retraining"
        finally:
            await conn.close()

    return asyncio.run(_check())


# ── Variables helper (env-backed, see init_airflow_variables.sh) ──
def v(key: str) -> str:
    from airflow.sdk import Variable
    return Variable.get(key)


def _detect_new_champion(**context) -> str:
    """Check if training promoted a new champion → recompute ref distributions."""
    from airflow.hooks.base import BaseHook

    pg_conn = BaseHook.get_connection("postgres_default")
    dsn = (
        f"postgresql://{pg_conn.login}:{pg_conn.password}"
        f"@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"
    )
    import asyncpg

    async def _check():
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT trained_at FROM model_registry WHERE alias = 'champion'",
            )
            if row and row["trained_at"]:
                trained_at = row["trained_at"]
                tz = trained_at.tzinfo
                now = datetime.now(tz) if tz else datetime.now()
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

    from drift.evidently_reporter import EvidentlyReporter  # type: ignore[import-untyped]
    from drift.repository import (  # type: ignore[import-untyped]
        create_drift_metric,
        generate_drift_run_id,
    )
    from drift.router import _build_current_dataframe, _build_reference_dataframe  # type: ignore[import-untyped]
    from drift.service import DriftDetector  # type: ignore[import-untyped]
    from drift.utils import build_s3_key, upload_report_to_s3  # type: ignore[import-untyped]
    from src.database.connection import connection_ctx  # type: ignore[import-untyped]

    async def _run():
        drift_run_id = generate_drift_run_id()
        current_period = datetime.now().strftime("%Y-%m-%d_%Y-%m-%d")

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
        lookback = datetime.now() - timedelta(days=7)
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
    from airflow.hooks.base import BaseHook

    pg_conn = BaseHook.get_connection("postgres_default")
    dsn = (
        f"postgresql://{pg_conn.login}:{pg_conn.password}"
        f"@{pg_conn.host}:{pg_conn.port}/{pg_conn.schema or 'stocklens'}"
    )
    import asyncpg

    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            # prediction_log > 90 days
            cutoff = datetime.now() - timedelta(days=90)
            result = await conn.execute(
                "DELETE FROM prediction_log WHERE created_at < $1", cutoff,
            )
            pl_count = int(result.split()[-1])

            # drift_metrics > 365 days
            dm_cutoff = datetime.now() - timedelta(days=365)
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
    start_date=datetime(2026, 7, 6),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),
    tags=["stocklens", "ml", "drift"],
) as dag:

    # ── Task 1: Check for new data (branching) ──
    check_data = BranchPythonOperator(
        task_id="check_new_ohlcv_data",
        python_callable=_check_new_ohlcv_data,
    )

    skip_retraining = EmptyOperator(task_id="skip_retraining")

    # ── Task 2: Train challenger (runs on GPU via ECS EcsRunTaskOperator) ──
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
    check_data >> [train_challenger, skip_retraining]
    train_challenger >> detect_new_champion >> [capture_reference, skip_reference]
    [capture_reference, skip_reference] >> run_drift >> cleanup
