"""Repository for drift_metrics CRUD operations."""

from __future__ import annotations

from uuid import uuid4

from src.database.connection import connection_ctx


def generate_drift_run_id() -> str:
    """Generate a unique drift run ID."""
    return str(uuid4())


async def create_drift_metric(
    drift_run_id: str,
    ticker: str,
    model_version: str,
    metric_type: str,
    feature_name: str,
    drift_score: float,
    alert_triggered: bool,
    reference_period: str | None = None,
    current_period: str | None = None,
    details: dict | None = None,
) -> int:
    """Insert a single drift metric row.

    Returns the new row ID.
    """
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO drift_metrics
                (drift_run_id, ticker, model_version, metric_type, feature_name,
                 drift_score, alert_triggered, reference_period, current_period,
                 details)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            drift_run_id,
            ticker,
            model_version,
            metric_type,
            feature_name,
            drift_score,
            alert_triggered,
            reference_period,
            current_period,
            details,
        )
        return row["id"]


async def get_latest_drift_summary() -> dict:
    """Get a summary of the most recent drift run.

    Returns a dict with ``overall_status``, ``drifted_features``,
    ``total_features``, ``latest_run_at``, and ``tickers_with_drift``.
    """
    async with connection_ctx() as conn:
        latest = await conn.fetchrow(
            """
            SELECT drift_run_id, MAX(created_at) as latest_run_at
            FROM drift_metrics
            GROUP BY drift_run_id
            ORDER BY latest_run_at DESC
            LIMIT 1
            """,
        )

    if not latest:
        return {
            "overall_status": "no_data",
            "drifted_features": 0,
            "total_features": 0,
            "latest_run_at": None,
            "tickers_with_drift": [],
        }

    drift_run_id = latest["drift_run_id"]
    latest_run_at = latest["latest_run_at"]

    async with connection_ctx() as conn:
        # Total distinct (ticker, feature_name) combos
        total = await conn.fetchval(
            "SELECT COUNT(DISTINCT (ticker, feature_name))"
            " FROM drift_metrics WHERE drift_run_id = $1",
            drift_run_id,
        )
        # Alerted combos
        drifted = await conn.fetchval(
            "SELECT COUNT(DISTINCT (ticker, feature_name))"
            " FROM drift_metrics"
            " WHERE drift_run_id = $1 AND alert_triggered = TRUE",
            drift_run_id,
        )
        # Tickers with at least one alert
        rows = await conn.fetch(
            "SELECT DISTINCT ticker"
            " FROM drift_metrics"
            " WHERE drift_run_id = $1 AND alert_triggered = TRUE",
            drift_run_id,
        )
        drifting_tickers = [r["ticker"] for r in rows]

    return {
        "drift_run_id": drift_run_id,
        "overall_status": "drifted" if drifted > 0 else "stable",
        "drifted_features": drifted or 0,
        "total_features": total or 0,
        "latest_run_at": (latest_run_at.isoformat() if latest_run_at else None),
        "tickers_with_drift": drifting_tickers,
    }


async def list_drift_runs(
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List recent drift runs, newest first.

    Returns a list of runs with aggregated alert counts.
    """
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            """
            SELECT
                drift_run_id,
                MAX(created_at) AS latest_run_at,
                COUNT(*) AS total_metrics,
                COUNT(*) FILTER (WHERE alert_triggered = TRUE) AS alerts
            FROM drift_metrics
            GROUP BY drift_run_id
            ORDER BY latest_run_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    return [
        {
            "drift_run_id": r["drift_run_id"],
            "latest_run_at": r["latest_run_at"].isoformat(),
            "total_metrics": r["total_metrics"],
            "alerts": r["alerts"],
        }
        for r in rows
    ]


async def get_drift_report_by_run(drift_run_id: str) -> list[dict]:
    """Get all metrics for a specific drift run."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            """
            SELECT ticker, feature_name, metric_type, drift_score,
                   alert_triggered, model_version, created_at
            FROM drift_metrics
            WHERE drift_run_id = $1
            ORDER BY ticker, feature_name
            """,
            drift_run_id,
        )

    return [
        {
            "ticker": r["ticker"],
            "feature_name": r["feature_name"],
            "metric_type": r["metric_type"],
            "drift_score": r["drift_score"],
            "alert_triggered": r["alert_triggered"],
            "model_version": r["model_version"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
