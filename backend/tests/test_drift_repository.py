"""
Tests for drift repository (src.drift.repository).

Uses real database via connection_ctx() with per-test transaction rollback.
"""

from __future__ import annotations

from src.drift.repository import (
    create_drift_metric,
    generate_drift_run_id,
    get_drift_report_by_run,
    get_latest_drift_summary,
    list_drift_runs,
)


class TestGenerateDriftRunId:
    """Tests for generate_drift_run_id."""

    def test_returns_uuid_string(self):
        run_id = generate_drift_run_id()
        assert isinstance(run_id, str)
        assert len(run_id) == 36  # UUID4 format

    def test_unique_ids(self):
        ids = {generate_drift_run_id() for _ in range(100)}
        assert len(ids) == 100


class TestCreateDriftMetric:
    """Tests for create_drift_metric."""

    async def test_inserts_metric_returns_id(self):
        metric_id = await create_drift_metric(
            drift_run_id="test-run-1",
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.15,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        assert isinstance(metric_id, int)
        assert metric_id > 0

    async def test_inserts_with_all_optional_fields(self):
        metric_id = await create_drift_metric(
            drift_run_id="test-run-2",
            ticker="MSFT",
            model_version="v2",
            metric_type="ks_statistic",
            feature_name="rsi_14",
            drift_score=0.25,
            alert_triggered=True,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
            details={"threshold": 0.3, "statistic": 0.25},
        )
        assert isinstance(metric_id, int)

    async def test_inserts_with_none_details(self):
        metric_id = await create_drift_metric(
            drift_run_id="test-run-3",
            ticker="GOOGL",
            model_version="v1",
            metric_type="js_divergence",
            feature_name="vol_30d",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
            details=None,
        )
        assert isinstance(metric_id, int)

    async def test_multiple_metrics_same_run(self):
        for i in range(5):
            await create_drift_metric(
                drift_run_id="test-run-multi",
                ticker="AAPL",
                model_version="v1",
                metric_type="psi",
                feature_name=f"feature_{i}",
                drift_score=0.1,
                alert_triggered=False,
                reference_period="training",
                current_period="2024-01-01_2024-01-07",
            )

        report = await get_drift_report_by_run("test-run-multi")
        assert len(report) == 5


class TestGetLatestDriftSummary:
    """Tests for get_latest_drift_summary."""

    async def test_no_data_returns_default(self):
        summary = await get_latest_drift_summary()
        assert summary["overall_status"] == "no_data"
        assert summary["drifted_features"] == 0
        assert summary["total_features"] == 0
        assert summary["latest_run_at"] is None
        assert summary["tickers_with_drift"] == []

    async def test_returns_summary_after_insert(self):
        run_id = "test-summary-run"
        await create_drift_metric(
            drift_run_id=run_id,
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.3,
            alert_triggered=True,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        await create_drift_metric(
            drift_run_id=run_id,
            ticker="MSFT",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )

        summary = await get_latest_drift_summary()
        assert summary["overall_status"] == "drifted"
        assert summary["drifted_features"] == 1
        assert summary["total_features"] == 2
        assert "AAPL" in summary["tickers_with_drift"]
        assert summary["latest_run_at"] is not None

    async def test_latest_run_selected(self):
        run1 = "run-older"
        run2 = "run-newer"

        await create_drift_metric(
            drift_run_id=run1,
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.3,
            alert_triggered=True,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        await create_drift_metric(
            drift_run_id=run2,
            ticker="MSFT",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )

        summary = await get_latest_drift_summary()
        assert summary["drift_run_id"] == run2
        assert summary["overall_status"] == "stable"


class TestListDriftRuns:
    """Tests for list_drift_runs."""

    async def test_empty_returns_empty_list(self):
        runs = await list_drift_runs()
        assert runs == []

    async def test_returns_runs_with_aggregated_counts(self):
        await create_drift_metric(
            drift_run_id="run-1",
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="f1",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        await create_drift_metric(
            drift_run_id="run-1",
            ticker="AAPL",
            model_version="v1",
            metric_type="ks",
            feature_name="f2",
            drift_score=0.2,
            alert_triggered=True,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )

        runs = await list_drift_runs(limit=10)
        assert len(runs) >= 1
        run = runs[0]
        assert run["drift_run_id"] == "run-1"
        assert run["total_metrics"] == 2
        assert run["alerts"] == 1
        assert "latest_run_at" in run

    async def test_pagination_works(self):
        for i in range(5):
            await create_drift_metric(
                drift_run_id=f"run-{i}",
                ticker="AAPL",
                model_version="v1",
                metric_type="psi",
                feature_name="f1",
                drift_score=0.1,
                alert_triggered=False,
                reference_period="training",
                current_period="2024-01-01_2024-01-07",
            )

        page1 = await list_drift_runs(limit=2, offset=0)
        page2 = await list_drift_runs(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["drift_run_id"] != page2[0]["drift_run_id"]

    async def test_ordered_by_latest_first(self):
        await create_drift_metric(
            drift_run_id="run-early",
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="f1",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        await create_drift_metric(
            drift_run_id="run-late",
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="f1",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )

        runs = await list_drift_runs(limit=10)
        assert runs[0]["drift_run_id"] == "run-late"
        assert runs[1]["drift_run_id"] == "run-early"


class TestGetDriftReportByRun:
    """Tests for get_drift_report_by_run."""

    async def test_returns_metrics_for_run(self):
        run_id = "test-report-run"
        await create_drift_metric(
            drift_run_id=run_id,
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="log_ret_1d",
            drift_score=0.15,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        await create_drift_metric(
            drift_run_id=run_id,
            ticker="AAPL",
            model_version="v1",
            metric_type="ks_statistic",
            feature_name="rsi_14",
            drift_score=0.25,
            alert_triggered=True,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )

        report = await get_drift_report_by_run(run_id)
        assert len(report) == 2
        assert report[0]["ticker"] == "AAPL"
        assert report[0]["metric_type"] in ("psi", "ks_statistic")
        assert "drift_score" in report[0]
        assert "alert_triggered" in report[0]

    async def test_unknown_run_returns_empty_list(self):
        report = await get_drift_report_by_run("nonexistent-run")
        assert report == []

    async def test_orders_by_ticker_feature_name(self):
        run_id = "test-order-run"
        await create_drift_metric(
            drift_run_id=run_id,
            ticker="MSFT",
            model_version="v1",
            metric_type="psi",
            feature_name="z_feature",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )
        await create_drift_metric(
            drift_run_id=run_id,
            ticker="AAPL",
            model_version="v1",
            metric_type="psi",
            feature_name="a_feature",
            drift_score=0.1,
            alert_triggered=False,
            reference_period="training",
            current_period="2024-01-01_2024-01-07",
        )

        report = await get_drift_report_by_run(run_id)
        assert report[0]["ticker"] == "AAPL"
        assert report[1]["ticker"] == "MSFT"
