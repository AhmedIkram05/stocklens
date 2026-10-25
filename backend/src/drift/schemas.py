"""Pydantic schemas for the drift detection module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DriftRunRequest(BaseModel):
    """Request to trigger a drift detection run."""

    tickers: list[str] | None = Field(
        None,
        description="Tickers to monitor. Defaults to portfolio tickers.",
    )
    lookback_days: int = Field(
        30,
        ge=1,
        le=90,
        description=(
            "Days of prediction logs to compare against reference. Capped at 90 "
            "to match prediction_log retention — longer windows would silently "
            "operate on truncated data."
        ),
    )
    generate_report: bool = Field(
        False,
        description="Generate an Evidently HTML report (requires evidently).",
    )


class DriftMetricResponse(BaseModel):
    """A single drift metric for one ticker, one feature, one metric type."""

    ticker: str
    feature_name: str
    metric_type: str
    drift_score: float
    alert_triggered: bool
    model_version: str
    reference_period: str | None = None
    current_period: str | None = None


class DriftRunResponse(BaseModel):
    """Response from a drift detection run."""

    drift_run_id: str
    tickers_monitored: list[str]
    total_metrics: int
    alerts_triggered: int
    max_psi: float
    max_js_divergence: float
    overall_drift_verdict: str
    report_url: str | None = None
    metrics: list[DriftMetricResponse]
    data_quality: dict | None = None
    created_at: datetime


class DriftReportSummary(BaseModel):
    """Summary of the latest drift status for dashboard display."""

    overall_status: str
    drifted_features: int
    total_features: int
    latest_run_at: str | None = None
    tickers_with_drift: list[str]
