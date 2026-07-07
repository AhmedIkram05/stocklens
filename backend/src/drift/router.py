"""
Drift detection endpoints.

POST /drift/run          — Trigger on-demand drift detection
GET  /drift/summary      — Latest drift summary (dashboard)
GET  /drift/runs         — List recent drift runs
GET  /drift/runs/{id}    — Get metrics for a specific run
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import get_current_user_id
from src.database.connection import connection_ctx
from src.drift.evidently_reporter import EvidentlyReporter
from src.drift.repository import (
    create_drift_metric,
    generate_drift_run_id,
    get_drift_report_by_run,
    get_latest_drift_summary,
    list_drift_runs,
)
from src.drift.schemas import (
    DriftMetricResponse,
    DriftReportSummary,
    DriftRunRequest,
    DriftRunResponse,
)
from src.drift.service import FEATURE_NAMES, DriftDetector
from src.drift.utils import build_s3_key, generate_presigned_url, upload_report_to_s3

logger = structlog.get_logger()

router = APIRouter(tags=["drift"])
detector = DriftDetector()

# ponytail: lazy reporter singleton — EvidentlyReporter raises if evidently
# is incompatible (NumPy 2.0). Defer construction so the router stays
# importable even without evidently installed.
_reporter: EvidentlyReporter | None = None


def _get_reporter() -> EvidentlyReporter:
    global _reporter
    if _reporter is None:
        _reporter = EvidentlyReporter()
    return _reporter


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
        async with connection_ctx() as conn:
            rows = await conn.fetch("SELECT DISTINCT ticker FROM holdings")
            tickers = [r["ticker"] for r in rows] + ["SPY"]

    # 2. Fetch reference distribution from champion model
    async with connection_ctx() as conn:
        champion_row = await conn.fetchrow(
            "SELECT mlflow_run_id, model_version, metrics"
            " FROM model_registry WHERE alias = 'champion'"
        )

    if not champion_row:
        raise HTTPException(
            status_code=503,
            detail="No champion model found \u2014 cannot run drift detection",
        )

    model_version = champion_row["model_version"] or "unknown"
    reference_dist = (
        champion_row["metrics"].get("reference_distributions", {})
        if champion_row["metrics"]
        else {}
    )

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
            **{k: v for k, v in metric.items() if k != "details"},
            details=metric.get("details"),
        )

    # 6. Generate Evidently report if requested
    report_url = None
    if request.generate_report and reference_dist:
        try:
            ref_df = _build_reference_dataframe(reference_dist)
            cur_df = _build_current_dataframe(prediction_logs)

            if ref_df is not None and cur_df is not None:
                report_path, report_id = _get_reporter().generate_drift_report(ref_df, cur_df)
                report_s3_key = build_s3_key(drift_run_id, f"drift_report_{report_id}.html")
                uploaded = upload_report_to_s3(report_path, report_s3_key)
                if uploaded:
                    report_url = generate_presigned_url(report_s3_key)
                    async with connection_ctx() as conn:
                        await conn.execute(
                            "UPDATE drift_metrics SET report_s3_key = $1 WHERE drift_run_id = $2",
                            report_s3_key,
                            drift_run_id,
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

    response_metrics = [DriftMetricResponse(**m) for m in drift_result["metrics"]]

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


# ---------------------------------------------------------------------------
# Helper functions for building DataFrames from reference distributions and
# prediction logs (used by both the router and the Airflow DAG).
# ---------------------------------------------------------------------------


def _build_reference_dataframe(reference_dist: dict) -> pd.DataFrame | None:
    """Build a pandas DataFrame from reference distribution histograms."""
    feature_histograms = reference_dist.get("feature_histograms", {})
    if not feature_histograms:
        return None

    n_samples = min(
        min(
            (len(v.get("values", [])) for v in feature_histograms.values()),
            default=100,
        ),
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
    all_rows: list[dict[str, float]] = []

    for ticker, logs in prediction_logs.items():
        for entry in logs:
            features_data = entry.get("features", {}) or {}
            stats = features_data.get("stats")
            if stats and "means" in stats:
                row: dict[str, float] = {}
                for i, value in enumerate(stats["means"]):
                    if i < len(FEATURE_NAMES):
                        row[FEATURE_NAMES[i]] = value
                if row:
                    all_rows.append(row)

    if not all_rows:
        return None

    return pd.DataFrame(all_rows)
