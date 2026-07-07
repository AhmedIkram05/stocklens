"""Tests for drift_metrics repository.

Integration tests (marked ``integration``) require a running PostgreSQL.
Unit tests use ``mock_connection_ctx`` from conftest.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.drift.repository import (
    generate_drift_run_id,
    get_drift_report_by_run,
    get_latest_drift_summary,
    list_drift_runs,
)


class TestGenerateDriftRunId:
    def test_returns_uuid_string(self) -> None:
        rid = generate_drift_run_id()
        assert isinstance(rid, str)
        assert len(rid) == 36

    def test_unique_ids(self) -> None:
        ids = {generate_drift_run_id() for _ in range(100)}
        assert len(ids) == 100


class TestGetLatestDriftSummary:
    @pytest.mark.integration
    async def test_no_data(self) -> None:
        """Integration: no drift_metrics rows → no_data summary."""
        summary = await get_latest_drift_summary()
        assert summary["overall_status"] == "no_data"

    async def test_no_data_mocked(
        self,
        mock_connection_ctx: AsyncMock,
    ) -> None:
        """Unit: mock returns None for latest run → no_data."""
        mock_connection_ctx.fetchrow.return_value = None
        summary = await get_latest_drift_summary()
        assert summary["overall_status"] == "no_data"

    @pytest.mark.integration
    async def test_with_data(self) -> None:
        """Integration: after inserting a metric, summary returns stable/0."""
        rid = generate_drift_run_id()
        # Assume alembic migrations have run (test DB is fresh)
        from src.drift.repository import create_drift_metric

        await create_drift_metric(
            drift_run_id=rid,
            ticker="SPY",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.05,
            alert_triggered=False,
            reference_period="training",
            current_period="2026-07-07_2026-07-07",
        )
        summary = await get_latest_drift_summary()
        assert summary["drift_run_id"] == rid


class TestListDriftRuns:
    @pytest.mark.integration
    async def test_empty(self) -> None:
        runs = await list_drift_runs()
        assert isinstance(runs, list)

    async def test_empty_mocked(self, mock_connection_ctx: AsyncMock) -> None:
        mock_connection_ctx.fetch.return_value = []
        runs = await list_drift_runs(limit=5, offset=0)
        assert runs == []


class TestGetDriftReportByRun:
    @pytest.mark.integration
    async def test_not_found(self) -> None:
        metrics = await get_drift_report_by_run("nonexistent-run-id")
        assert metrics == []

    async def test_not_found_mocked(
        self,
        mock_connection_ctx: AsyncMock,
    ) -> None:
        mock_connection_ctx.fetch.return_value = []
        metrics = await get_drift_report_by_run("fake-id")
        assert metrics == []
