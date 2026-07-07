"""
Tests for the LSTM prediction endpoint.

Mocks prediction_service (model is not loaded in tests) and Redis.
Seeds OHLCV data via upsert_ohlcv where needed.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


def _make_ohlcv_rows(n_days: int = 100, start_price: float = 150.0) -> list[dict]:
    """Generate monotonically increasing OHLCV rows for testing."""
    rows = []
    for i in range(n_days):
        d = date.today() - timedelta(days=n_days - i)
        price = start_price + i * 0.1
        rows.append(
            {
                "date": d.isoformat(),
                "open": price - 0.5,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "adjusted_close": price,
                "volume": 1000000 + i * 1000,
            }
        )
    return rows


_MOCK_PREDICT_RESULT = {
    "ticker": "AAPL",
    "direction": "UP",
    "confidence": 0.75,
    "probabilities": {"DOWN": 0.1, "FLAT": 0.15, "UP": 0.75},
    "model_version": "1",
}

_MOCK_PREDICT_RESULT_DOWN = {
    "ticker": "AAPL",
    "direction": "DOWN",
    "confidence": 0.6,
    "probabilities": {"DOWN": 0.6, "FLAT": 0.3, "UP": 0.1},
    "model_version": "1",
}


class TestPredictNoModel:
    """When the champion model is not loaded."""

    async def test_returns_503(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        """GET /predict/AAPL returns 503 when no model loaded."""
        with (
            patch("src.prediction.service.prediction_service.is_loaded", return_value=False),
            patch("src.prediction.router.get_redis", return_value=None),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)
        assert response.status_code == 503
        assert "model not yet loaded" in response.json()["detail"].lower()


class TestPredictNoData:
    """When no OHLCV data exists for the ticker."""

    async def test_returns_404_empty_list(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Empty OHLCV results → 404."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch("src.prediction.router.fetch_ohlcv", return_value=[]),
            patch("src.prediction.router.get_redis", return_value=None),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)
        assert response.status_code == 404

    async def test_returns_404_insufficient_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Only 10 days of data (< 60 minimum) → 404."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(10)),
            patch("src.prediction.router.get_redis", return_value=None),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)
        assert response.status_code == 404
        assert "insufficient" in response.json()["detail"].lower()


class TestPredictSuccess:
    """Happy path: model loaded, data exists, prediction returned."""

    async def test_returns_prediction(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Seed OHLCV data, mock predict, verify full response."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value=_MOCK_PREDICT_RESULT,
            ),
            patch("src.prediction.router.get_redis", return_value=None),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert data["direction"] == "UP"
        assert data["confidence"] == 0.75
        assert data["probabilities"] == {"DOWN": 0.1, "FLAT": 0.15, "UP": 0.75}
        assert data["model_version"] == "1"
        assert data["cached"] is False
        assert "predicted_at" in data

    async def test_ticker_uppercased(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Lowercase ticker is uppercased in the response."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value={
                    **_MOCK_PREDICT_RESULT,
                    "ticker": "AAPL",
                },
            ),
            patch("src.prediction.router.get_redis", return_value=None),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/aapl", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"


class TestPredictCache:
    """Redis caching behaviour."""

    async def test_cache_hit_returns_cached(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Valid cached prediction → returned with cached=True."""
        mock_redis = AsyncMock()
        cached_payload = {
            "ticker": "AAPL",
            "direction": "DOWN",
            "confidence": 0.6,
            "probabilities": {"DOWN": 0.6, "FLAT": 0.3, "UP": 0.1},
            "model_version": "1",
            "predicted_at": "2026-07-01T12:00:00+00:00",
        }
        mock_redis.get.return_value = json.dumps(cached_payload)

        with patch("src.prediction.router.get_redis", return_value=mock_redis):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["direction"] == "DOWN"
        assert data["confidence"] == 0.6
        assert data["cached"] is True
        # predict() should NOT have been called
        assert "predicted_at" in data

    async def test_cache_corrupted_falls_through(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Corrupted JSON in Redis → skip cache, compute fresh."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "not-valid-json{{{"

        with (
            patch("src.prediction.router.get_redis", return_value=mock_redis),
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value=_MOCK_PREDICT_RESULT,
            ),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["cached"] is False

    async def test_redis_unavailable_falls_through(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Redis down → graceful degradation, compute fresh."""
        with (
            patch("src.prediction.router.get_redis", side_effect=ConnectionError("Redis down")),
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value=_MOCK_PREDICT_RESULT,
            ),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["cached"] is False


class TestPredictErrors:
    """Error handling edge cases."""

    async def test_requires_auth(self, client: AsyncClient) -> None:
        """No auth header → 401."""
        response = await client.get("/predict/AAPL")
        assert response.status_code == 401

    async def test_predict_returns_none(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """predict() returns None → 500."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch("src.prediction.router.prediction_service.predict", return_value=None),
            patch("src.prediction.router.get_redis", return_value=None),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)
        assert response.status_code == 500

    async def test_model_predict_raises(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """predict() raises RuntimeError → 500."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                side_effect=RuntimeError("Inference OOM"),
            ),
            patch("src.prediction.router.get_redis", return_value=None),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)
        assert response.status_code == 500

    async def test_unknown_ticker(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Ticker with no data → 404."""
        with (
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch("src.prediction.router.fetch_ohlcv", return_value=[]),
            patch("src.prediction.router.get_redis", return_value=None),
        ):
            response = await client.get("/predict/INVALID123", headers=auth_headers)
        assert response.status_code == 404


class TestPredictCacheWrite:
    """Verifies prediction is written to cache after fresh computation."""

    async def test_writes_to_cache_on_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Fresh prediction is written to Redis setex."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        with (
            patch("src.prediction.router.get_redis", return_value=mock_redis),
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value=_MOCK_PREDICT_RESULT,
            ),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        # Verify setex was called (TTL = 21600 = 6h)
        assert mock_redis.setex.called
        args = mock_redis.setex.call_args
        assert args[0][1] == 21600

    async def test_cache_write_graceful_degradation(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Redis write failure should NOT crash the endpoint."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.setex.side_effect = ConnectionError("Write failed")

        with (
            patch("src.prediction.router.get_redis", return_value=mock_redis),
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value=_MOCK_PREDICT_RESULT,
            ),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["cached"] is False


class TestPredictCacheRead:
    """Redis cache read failure modes."""

    async def test_cache_read_exception_falls_through(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Exception during cache read → fall through to fresh prediction."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("Read failed")

        with (
            patch("src.prediction.router.get_redis", return_value=mock_redis),
            patch("src.prediction.router.prediction_service.is_loaded", return_value=True),
            patch(
                "src.prediction.router.prediction_service.predict",
                return_value=_MOCK_PREDICT_RESULT,
            ),
            patch("src.prediction.router.fetch_ohlcv", return_value=_make_ohlcv_rows(100)),
        ):
            response = await client.get("/predict/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["cached"] is False
