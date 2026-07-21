"""
Tests for drift router endpoints (src.drift.router).

Tests API endpoints with mocked dependencies and auth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class TestTriggerDriftRun:
    """Tests for POST /drift/run."""

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router._get_reporter")
    @patch("src.drift.router.upload_report_to_s3")
    @patch("src.drift.router.generate_presigned_url")
    @patch("src.drift.router.build_s3_key")
    @patch("src.drift.router._build_current_dataframe")
    @patch("src.drift.router._build_reference_dataframe")
    @patch("src.drift.router.create_drift_metric")
    @patch("src.drift.router.DriftDetector.compute_drift")
    @patch("src.drift.router.connection_ctx")
    @patch("src.drift.router.generate_drift_run_id")
    async def test_trigger_drift_run_happy_path(
        self,
        mock_run_id,
        mock_conn_ctx,
        mock_compute_drift,
        mock_create_metric,
        mock_build_ref,
        mock_build_cur,
        mock_s3_key,
        mock_presigned,
        mock_upload,
        mock_reporter,
        mock_get_user,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):

        mock_get_user.return_value = "test-user"
        mock_run_id.return_value = "test-run-123"

        # Mock DB connection
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "mlflow_run_id": "mlflow-1",
            "model_version": "v1.0",
            "metrics": {"reference_distributions": {"feature_histograms": {}}},
        }
        mock_conn.fetch.return_value = []
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        # Mock drift computation
        mock_compute_drift.return_value = {
            "metrics": [
                {
                    "ticker": "AAPL",
                    "model_version": "v1.0",
                    "metric_type": "psi",
                    "feature_name": "log_ret_1d",
                    "drift_score": 0.1,
                    "alert_triggered": False,
                    "reference_period": "training",
                    "current_period": "2024-01-01_2024-01-07",
                    "details": None,
                }
            ],
            "alerts_triggered": 0,
            "max_psi": 0.1,
            "max_js_divergence": 0.05,
            "overall_verdict": "stable",
        }

        mock_build_ref.return_value = None
        mock_build_cur.return_value = None

        response = await client.post(
            "/drift/run",
            json={"tickers": ["AAPL"], "lookback_days": 7, "generate_report": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["drift_run_id"] == "test-run-123"
        assert data["tickers_monitored"] == ["AAPL"]
        assert data["total_metrics"] == 1
        assert data["alerts_triggered"] == 0
        assert data["overall_drift_verdict"] == "stable"

    async def test_requires_auth(self, client: AsyncClient):
        response = await client.post("/drift/run", json={"tickers": ["AAPL"]})
        assert response.status_code == 401

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.connection_ctx")
    async def test_no_champion_model_returns_503(
        self, mock_conn_ctx, mock_get_user, client: AsyncClient, auth_headers: dict[str, str]
    ):
        mock_get_user.return_value = "test-user"
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        response = await client.post("/drift/run", json={"tickers": ["AAPL"]}, headers=auth_headers)

        assert response.status_code == 503
        assert "champion model" in response.json()["detail"].lower()

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.connection_ctx")
    @patch("src.drift.router.DriftDetector.compute_drift")
    @patch("src.drift.router.generate_drift_run_id")
    async def test_uses_portfolio_tickers_when_not_specified(
        self,
        mock_run_id,
        mock_compute_drift,
        mock_conn_ctx,
        mock_get_user,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        mock_get_user.return_value = "test-user"
        mock_run_id.return_value = "test-run"

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "mlflow_run_id": "mlflow-1",
            "model_version": "v1",
            "metrics": {"reference_distributions": {}},
        }
        mock_conn.fetch.side_effect = [
            [{"ticker": "AAPL"}, {"ticker": "MSFT"}],  # holdings
            [],  # prediction_log
        ]
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        mock_compute_drift.return_value = {
            "metrics": [],
            "alerts_triggered": 0,
            "max_psi": 0.0,
            "max_js_divergence": 0.0,
            "overall_verdict": "stable",
        }

        response = await client.post("/drift/run", json={"lookback_days": 7}, headers=auth_headers)

        assert response.status_code == 200
        # Should have portfolio tickers + SPY
        assert "SPY" in response.json()["tickers_monitored"]


class TestGetDriftSummary:
    """Tests for GET /drift/summary."""

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.get_latest_drift_summary")
    async def test_get_summary_success(
        self, mock_summary, mock_get_user, client: AsyncClient, auth_headers: dict[str, str]
    ):
        mock_get_user.return_value = "test-user"
        mock_summary.return_value = {
            "drift_run_id": "run-1",
            "overall_status": "drifted",
            "drifted_features": 5,
            "total_features": 20,
            "latest_run_at": datetime.now(timezone.utc).isoformat(),
            "tickers_with_drift": ["AAPL", "MSFT"],
        }

        response = await client.get("/drift/summary", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "drifted"
        assert data["drifted_features"] == 5
        assert data["total_features"] == 20
        assert "AAPL" in data["tickers_with_drift"]

    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/drift/summary")
        assert response.status_code == 401


class TestListRecentRuns:
    """Tests for GET /drift/runs."""

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.list_drift_runs")
    async def test_list_runs_success(
        self, mock_list, mock_get_user, client: AsyncClient, auth_headers: dict[str, str]
    ):
        mock_get_user.return_value = "test-user"
        mock_list.return_value = [
            {
                "drift_run_id": "run-1",
                "latest_run_at": datetime.now(timezone.utc).isoformat(),
                "total_metrics": 10,
                "alerts": 2,
            },
            {
                "drift_run_id": "run-2",
                "latest_run_at": datetime.now(timezone.utc).isoformat(),
                "total_metrics": 8,
                "alerts": 0,
            },
        ]

        response = await client.get("/drift/runs", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["drift_run_id"] == "run-1"
        assert data[0]["alerts"] == 2

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.list_drift_runs")
    async def test_pagination_params_passed(
        self, mock_list, mock_get_user, client: AsyncClient, auth_headers: dict[str, str]
    ):
        mock_get_user.return_value = "test-user"
        mock_list.return_value = []

        await client.get("/drift/runs?limit=5&offset=10", headers=auth_headers)

        mock_list.assert_called_once_with(limit=5, offset=10)

    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/drift/runs")
        assert response.status_code == 401


class TestGetRunDetails:
    """Tests for GET /drift/runs/{drift_run_id}."""

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.get_drift_report_by_run")
    async def test_get_run_details_success(
        self, mock_report, mock_get_user, client: AsyncClient, auth_headers: dict[str, str]
    ):
        mock_get_user.return_value = "test-user"
        mock_report.return_value = [
            {
                "ticker": "AAPL",
                "feature_name": "log_ret_1d",
                "metric_type": "psi",
                "drift_score": 0.15,
                "alert_triggered": False,
                "model_version": "v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ]

        response = await client.get("/drift/runs/run-123", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["ticker"] == "AAPL"

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.get_drift_report_by_run")
    async def test_not_found_returns_404(
        self, mock_report, mock_get_user, client: AsyncClient, auth_headers: dict[str, str]
    ):
        mock_get_user.return_value = "test-user"
        mock_report.return_value = []

        response = await client.get("/drift/runs/nonexistent", headers=auth_headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/drift/runs/some-id")
        assert response.status_code == 401


class TestBuildReferenceDataframe:
    """Tests for _build_reference_dataframe helper."""

    def test_empty_feature_histograms_returns_none(self):
        from src.drift.router import _build_reference_dataframe

        assert _build_reference_dataframe({}) is None

    def test_empty_histograms_dict_returns_none(self):
        from src.drift.router import _build_reference_dataframe

        assert _build_reference_dataframe({"feature_histograms": {}}) is None

    def test_builds_dataframe_from_histograms(self):
        import pandas as pd

        from src.drift.router import _build_reference_dataframe

        result = _build_reference_dataframe(
            {
                "feature_histograms": {
                    "log_ret_1d": {"values": [0.1, 0.2, 0.3]},
                    "rsi_14": {"values": [50.0, 55.0, 60.0]},
                }
            }
        )
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["log_ret_1d", "rsi_14"]
        assert len(result) == 3

    def test_truncates_at_1000_samples(self):
        from src.drift.router import _build_reference_dataframe

        values = list(range(2000))
        result = _build_reference_dataframe({"feature_histograms": {"f1": {"values": values}}})
        assert result is not None
        assert len(result) == 1000

    def test_uneven_feature_lengths_uses_min(self):
        from src.drift.router import _build_reference_dataframe

        result = _build_reference_dataframe(
            {
                "feature_histograms": {
                    "f1": {"values": [1, 2, 3]},
                    "f2": {"values": [4, 5]},
                }
            }
        )
        assert result is not None
        assert len(result) == 2

    def test_empty_values_result_has_zero_rows(self):
        """Empty value lists produce a 0-row DataFrame (n_samples=0)."""
        import pandas as pd

        from src.drift.router import _build_reference_dataframe

        result = _build_reference_dataframe({"feature_histograms": {"f1": {"values": []}}})
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestBuildCurrentDataframe:
    """Tests for _build_current_dataframe helper."""

    def test_empty_logs_returns_none(self):
        from src.drift.router import _build_current_dataframe

        assert _build_current_dataframe({}) is None

    def test_logs_without_features_skipped(self):
        from src.drift.router import _build_current_dataframe

        logs = {"AAPL": [{"ticker": "AAPL", "features": None}]}
        assert _build_current_dataframe(logs) is None

    def test_builds_dataframe_from_logs(self):
        import pandas as pd

        from src.drift.router import _build_current_dataframe

        logs = {
            "AAPL": [
                {
                    "features": {
                        "stats": {"means": [0.5, 0.3]},
                    }
                }
            ]
        }
        result = _build_current_dataframe(logs)
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_features_without_stats_skipped(self):
        from src.drift.router import _build_current_dataframe

        logs = {"AAPL": [{"features": {"no_stats": True}}]}
        assert _build_current_dataframe(logs) is None


class TestReportGenerationPath:
    """Tests for the Evidently report generation path in trigger_drift_run."""

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router._get_reporter")
    @patch("src.drift.router.upload_report_to_s3")
    @patch("src.drift.router.generate_presigned_url")
    @patch("src.drift.router.build_s3_key")
    @patch("src.drift.router._build_current_dataframe")
    @patch("src.drift.router._build_reference_dataframe")
    @patch("src.drift.router.create_drift_metric")
    @patch("src.drift.router.DriftDetector.compute_drift")
    @patch("src.drift.router.connection_ctx")
    @patch("src.drift.router.generate_drift_run_id")
    async def test_generate_report_happy_path(
        self,
        mock_run_id,
        mock_conn_ctx,
        mock_compute_drift,
        mock_create_metric,
        mock_build_ref,
        mock_build_cur,
        mock_s3_key,
        mock_presigned,
        mock_upload,
        mock_reporter,
        mock_get_user,
        client,
        auth_headers,
    ):
        """When generate_report=True and reference_dist has histograms, report is generated."""
        mock_get_user.return_value = "test-user"
        mock_run_id.return_value = "test-run-456"

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "mlflow_run_id": "mlflow-1",
            "model_version": "v1.0",
            "metrics": {
                "reference_distributions": {
                    "feature_histograms": {"log_ret_1d": {"values": [0.1, 0.2]}}
                }
            },
        }
        mock_conn.fetch.return_value = []
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        mock_compute_drift.return_value = {
            "metrics": [],
            "alerts_triggered": 0,
            "max_psi": 0.0,
            "max_js_divergence": 0.0,
            "overall_verdict": "stable",
        }

        # Report generation mocks
        import pandas as pd

        ref_df = pd.DataFrame({"f1": [0.1]})
        cur_df = pd.DataFrame({"f1": [0.2]})
        mock_build_ref.return_value = ref_df
        mock_build_cur.return_value = cur_df

        mock_reporter.return_value.generate_drift_report.return_value = (
            "/tmp/report.html",
            "report-id-1",
        )
        mock_s3_key.return_value = "drift_reports/2024-01-01/drift_report_report-id-1.html"
        mock_upload.return_value = True
        mock_presigned.return_value = "https://presigned.url"

        response = await client.post(
            "/drift/run",
            json={"tickers": ["AAPL"], "lookback_days": 7, "generate_report": True},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["report_url"] == "https://presigned.url"
        mock_reporter.return_value.generate_drift_report.assert_called_once_with(ref_df, cur_df)
        mock_upload.assert_called_once()
        mock_presigned.assert_called_once()

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router._get_reporter")
    @patch("src.drift.router._build_current_dataframe")
    @patch("src.drift.router._build_reference_dataframe")
    @patch("src.drift.router.create_drift_metric")
    @patch("src.drift.router.DriftDetector.compute_drift")
    @patch("src.drift.router.connection_ctx")
    @patch("src.drift.router.generate_drift_run_id")
    async def test_report_skipped_when_ref_df_none(
        self,
        mock_run_id,
        mock_conn_ctx,
        mock_compute_drift,
        mock_create_metric,
        mock_build_ref,
        mock_build_cur,
        mock_reporter,
        mock_get_user,
        client,
        auth_headers,
    ):
        """When _build_reference_dataframe returns None, report is skipped."""
        mock_get_user.return_value = "test-user"
        mock_run_id.return_value = "test-run-789"

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "mlflow_run_id": "mlflow-1",
            "model_version": "v1.0",
            "metrics": {"reference_distributions": {}},
        }
        mock_conn.fetch.return_value = []
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        mock_compute_drift.return_value = {
            "metrics": [],
            "alerts_triggered": 0,
            "max_psi": 0.0,
            "max_js_divergence": 0.0,
            "overall_verdict": "stable",
        }

        mock_build_ref.return_value = None

        response = await client.post(
            "/drift/run",
            json={"tickers": ["AAPL"], "generate_report": True},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["report_url"] is None
        mock_reporter.return_value.generate_drift_report.assert_not_called()

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.connection_ctx")
    @patch("src.drift.router.DriftDetector.compute_drift")
    @patch("src.drift.router.generate_drift_run_id")
    async def test_empty_drift_data_returns_stable(
        self,
        mock_run_id,
        mock_compute_drift,
        mock_conn_ctx,
        mock_get_user,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        mock_get_user.return_value = "test-user"
        mock_run_id.return_value = "test-run"

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "mlflow_run_id": "mlflow-1",
            "model_version": "v1",
            "metrics": {"reference_distributions": {}},
        }
        mock_conn.fetch.return_value = []
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        mock_compute_drift.return_value = {
            "metrics": [],
            "alerts_triggered": 0,
            "max_psi": 0.0,
            "max_js_divergence": 0.0,
            "overall_verdict": "stable",
        }

        response = await client.post("/drift/run", json={"tickers": ["AAPL"]}, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["overall_drift_verdict"] == "stable"
        assert response.json()["total_metrics"] == 0

    @patch("src.drift.router.get_current_user_id")
    @patch("src.drift.router.connection_ctx")
    @patch("src.drift.router.DriftDetector.compute_drift")
    @patch("src.drift.router.generate_drift_run_id")
    async def test_alerts_triggered_logged(
        self,
        mock_run_id,
        mock_compute_drift,
        mock_conn_ctx,
        mock_get_user,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):

        mock_get_user.return_value = "test-user"
        mock_run_id.return_value = "test-run"

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "mlflow_run_id": "mlflow-1",
            "model_version": "v1",
            "metrics": {
                "reference_distributions": {
                    "feature_histograms": {"log_ret_1d": {"values": [0.0] * 10}}
                }
            },
        }
        mock_conn.fetch.return_value = []
        mock_conn_ctx.return_value.__aenter__.return_value = mock_conn

        mock_compute_drift.return_value = {
            "metrics": [
                {
                    "ticker": "AAPL",
                    "model_version": "v1",
                    "metric_type": "psi",
                    "feature_name": "log_ret_1d",
                    "drift_score": 0.5,
                    "alert_triggered": True,
                    "reference_period": "training",
                    "current_period": "2024-01-01_2024-01-07",
                    "details": None,
                }
            ],
            "alerts_triggered": 1,
            "max_psi": 0.5,
            "max_js_divergence": 0.0,
            "overall_verdict": "drifted",
        }

        with patch("src.drift.router.logger.warning") as mock_warn:
            response = await client.post(
                "/drift/run", json={"tickers": ["AAPL"]}, headers=auth_headers
            )

            assert response.status_code == 200
            assert response.json()["alerts_triggered"] == 1
            mock_warn.assert_called()
            call_args = mock_warn.call_args
            assert "drift_alerts_triggered" in call_args[0]
            assert call_args[1]["alerts"] == 1
