"""Tests for drift detection API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

# ── Auth tests (no valid token) ───────────────────────────────────────────────


class TestDriftRouterAuth:
    """Every endpoint must return 401 without a valid auth token."""

    async def test_post_drift_run_no_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/drift/run", json={})
        assert resp.status_code == 401

    async def test_get_drift_summary_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/drift/summary")
        assert resp.status_code == 401

    async def test_get_drift_runs_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/drift/runs")
        assert resp.status_code == 401

    async def test_get_drift_run_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/drift/runs/some-id")
        assert resp.status_code == 401


# ── Authenticated tests ──────────────────────────────────────────────────────


class TestDriftRouterWithAuth:
    """Authenticated requests with mocked repository layer."""

    async def test_post_drift_run_no_champion(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """No champion model in DB → 503."""
        with patch("src.drift.router.connection_ctx") as mock_ctx:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value=None)
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value = mock_cm
            resp = await client.post(
                "/drift/run",
                json={},
                headers=auth_headers,
            )
        assert resp.status_code == 503
        assert "champion model" in resp.text.lower()

    async def test_get_drift_summary_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Empty drift_metrics table returns no_data summary."""
        with patch(
            "src.drift.router.get_latest_drift_summary",
            return_value={
                "overall_status": "no_data",
                "drifted_features": 0,
                "total_features": 0,
                "latest_run_at": None,
                "tickers_with_drift": [],
            },
        ):
            resp = await client.get("/drift/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_status"] == "no_data"
        assert data["drifted_features"] == 0

    async def test_get_drift_summary_healthy(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Stable state returns stable status."""
        with patch(
            "src.drift.router.get_latest_drift_summary",
            return_value={
                "overall_status": "stable",
                "drifted_features": 0,
                "total_features": 5,
                "latest_run_at": "2026-07-07T12:00:00+00:00",
                "tickers_with_drift": [],
            },
        ):
            resp = await client.get("/drift/summary", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["overall_status"] == "stable"

    async def test_get_drift_runs_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Empty table returns []."""
        with patch("src.drift.router.list_drift_runs", return_value=[]):
            resp = await client.get("/drift/runs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_drift_run_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Found run returns its metrics."""
        mock_metrics = [
            {
                "ticker": "SPY",
                "feature_name": "log_ret_1d",
                "metric_type": "psi",
                "drift_score": 0.05,
                "alert_triggered": False,
                "model_version": "v1",
                "created_at": "2026-07-07T12:00:00+00:00",
            },
        ]
        with patch(
            "src.drift.router.get_drift_report_by_run",
            return_value=mock_metrics,
        ):
            resp = await client.get(
                "/drift/runs/some-run-id",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ticker"] == "SPY"

    async def test_get_drift_run_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Unknown run ID returns 404."""
        with patch(
            "src.drift.router.get_drift_report_by_run",
            return_value=[],
        ):
            resp = await client.get(
                "/drift/runs/unknown-run-id",
                headers=auth_headers,
            )
        assert resp.status_code == 404

    async def test_get_drift_run_no_auth_with_patch(
        self,
        client: AsyncClient,
    ) -> None:
        """Even with mocked metrics, no auth → 401."""
        with patch(
            "src.drift.router.get_drift_report_by_run",
            return_value=[{"ticker": "SPY"}],
        ):
            resp = await client.get("/drift/runs/some-id")
        assert resp.status_code == 401
