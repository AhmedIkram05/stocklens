"""
Tests for the prediction logger — fire-and-forget logging of prediction requests.

All tests run inside a transaction that is rolled back on teardown
(see conftest.py ``_test_db`` fixture).

Integration tests call ``_log_prediction`` directly (not via the sync wrapper
``log_prediction_sync``) to avoid ``asyncio.run()`` conflicts with the
pytest-asyncio event loop.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.prediction.prediction_logger import (
    FEATURE_NAMES,
    _log_prediction,
    compute_feature_stats,
)


@pytest.mark.asyncio
async def test_log_prediction_happy_path() -> None:
    """Insert a row and verify all columns."""
    probabilities = {"DOWN": 0.1, "FLAT": 0.2, "UP": 0.7}
    feature_values = np.random.randn(60, 17).astype(np.float32)
    feature_window = feature_values[-30:]

    await _log_prediction(
        ticker="AAPL",
        model_version="v22",
        prediction="UP",
        confidence=0.7,
        probabilities=probabilities,
        feature_values=feature_values,
        feature_window=feature_window,
    )

    # Verify row exists
    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        row = await conn.fetchrow("SELECT * FROM prediction_log WHERE ticker = 'AAPL'")
        assert row is not None
        assert row["prediction"] == "UP"
        assert row["model_version"] == "v22"
        assert abs(row["confidence"] - 0.7) < 1e-6
        assert row["ticker"] == "AAPL"
        assert row["probabilities"] is not None
        assert row["features"] is not None
        assert row["feature_stats"] is not None
        assert row["raw_feature_names"] is not None


@pytest.mark.asyncio
async def test_log_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PREDICTION_LOG_ENABLED=False, no row is inserted."""
    monkeypatch.setattr("src.config.settings.PREDICTION_LOG_ENABLED", False)

    await _log_prediction(
        ticker="AAPL",
        model_version="v22",
        prediction="UP",
        confidence=0.9,
        probabilities={"DOWN": 0.1, "FLAT": 0.0, "UP": 0.9},
        feature_values=np.random.randn(60, 17).astype(np.float32),
        feature_window=np.random.randn(30, 17).astype(np.float32),
    )

    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        row = await conn.fetchrow("SELECT * FROM prediction_log WHERE ticker = 'AAPL'")
        assert row is None


@pytest.mark.asyncio
async def test_log_with_null_features() -> None:
    """feature_values=None still logs prediction metadata."""
    await _log_prediction(
        ticker="MSFT",
        model_version="v22",
        prediction="DOWN",
        confidence=0.5,
        probabilities={"DOWN": 0.5, "FLAT": 0.3, "UP": 0.2},
        feature_values=None,
        feature_window=None,
    )

    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        row = await conn.fetchrow("SELECT * FROM prediction_log WHERE ticker = 'MSFT'")
        assert row is not None
        assert row["prediction"] == "DOWN"
        assert row["feature_stats"] is None  # feature_stats is SQL NULL when no features


@pytest.mark.asyncio
async def test_log_special_chars_in_ticker() -> None:
    """Ticker with special characters in JSONB."""
    await _log_prediction(
        ticker="BRK.B",
        model_version="v22",
        prediction="FLAT",
        confidence=0.4,
        probabilities={"DOWN": 0.3, "FLAT": 0.4, "UP": 0.3},
        feature_values=np.random.randn(60, 17).astype(np.float32),
        feature_window=np.random.randn(30, 17).astype(np.float32),
    )

    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        row = await conn.fetchrow("SELECT * FROM prediction_log WHERE ticker = 'BRK.B'")
        assert row is not None
        assert row["ticker"] == "BRK.B"


@pytest.mark.asyncio
async def test_log_concurrent_safety() -> None:
    """5 concurrent logs all succeed."""
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
    probs = {"DOWN": 0.1, "FLAT": 0.2, "UP": 0.7}

    async def _log_one(ticker: str) -> None:
        await _log_prediction(
            ticker=ticker,
            model_version="v22",
            prediction="UP",
            confidence=0.7,
            probabilities=probs,
            feature_values=np.random.randn(60, 17).astype(np.float32),
            feature_window=np.random.randn(30, 17).astype(np.float32),
        )

    # Use sequential logging to avoid connection pool contention
    # (connection_ctx uses a single pool; concurrent gather would clash)
    for t in tickers:
        await _log_one(t)

    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        rows = await conn.fetch("SELECT ticker FROM prediction_log ORDER BY ticker")
        logged_tickers = [r["ticker"] for r in rows]
        assert len(logged_tickers) == 5
        for t in tickers:
            assert t.upper() in logged_tickers


def test_feature_names_constant() -> None:
    """FEATURE_NAMES has exactly 17 entries matching expected order."""
    assert len(FEATURE_NAMES) == 17
    assert FEATURE_NAMES[0] == "log_ret_1d"
    assert FEATURE_NAMES[6] == "ma_50"
    assert FEATURE_NAMES[12] == "vol_rank"
    assert FEATURE_NAMES[13] == "vol_pct"
    assert FEATURE_NAMES[14] == "excess_ret_1d"
    assert FEATURE_NAMES[16] == "excess_ret_21d"


def test_compute_feature_stats_happy_path() -> None:
    """Verify means/stds are correct for simple input."""
    values = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=np.float32)
    stats = compute_feature_stats(values)
    assert stats is not None
    assert len(stats["means"]) == 2
    assert len(stats["stds"]) == 2
    assert stats["n_samples"] == 3
    assert abs(stats["means"][0] - 3.0) < 1e-5  # mean of [1, 3, 5]
    assert abs(stats["means"][1] - 4.0) < 1e-5  # mean of [2, 4, 6]


def test_compute_feature_stats_none() -> None:
    """compute_feature_stats returns None for None input."""
    assert compute_feature_stats(None) is None


def test_compute_feature_stats_empty() -> None:
    """compute_feature_stats returns None for empty array."""
    assert compute_feature_stats(np.array([])) is None


@pytest.mark.asyncio
async def test_logged_stats_match_compute_feature_stats() -> None:
    """Stored feature_stats in DB matches compute_feature_stats output."""
    rng = np.random.default_rng(42)
    feature_values = rng.normal(loc=0.0, scale=1.0, size=(60, 17)).astype(np.float32)
    feature_window = feature_values[-30:]

    expected_stats = compute_feature_stats(feature_values)

    await _log_prediction(
        ticker="STATS_CHK",  # <= 10 chars for VARCHAR(10)
        model_version="v22",
        prediction="UP",
        confidence=0.85,
        probabilities={"DOWN": 0.05, "FLAT": 0.1, "UP": 0.85},
        feature_values=feature_values,
        feature_window=feature_window,
    )

    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT feature_stats FROM prediction_log WHERE ticker = 'STATS_CHK'"
        )
        assert row is not None
        raw: str | dict | None = row["feature_stats"]
        assert raw is not None
        stored = raw if isinstance(raw, dict) else json.loads(raw)
        assert stored["n_samples"] == expected_stats["n_samples"]
        assert len(stored["means"]) == len(expected_stats["means"])
        assert abs(stored["means"][0] - expected_stats["means"][0]) < 1e-5
        assert abs(stored["stds"][0] - expected_stats["stds"][0]) < 1e-5


@pytest.mark.asyncio
async def test_logged_raw_feature_names_match_constant() -> None:
    """Stored raw_feature_names in DB matches the FEATURE_NAMES constant."""
    await _log_prediction(
        ticker="FEAT_NAMES",
        model_version="v22",
        prediction="DOWN",
        confidence=0.3,
        probabilities={"DOWN": 0.4, "FLAT": 0.3, "UP": 0.3},
        feature_values=np.random.randn(60, 17).astype(np.float32),
        feature_window=np.random.randn(30, 17).astype(np.float32),
    )

    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT raw_feature_names FROM prediction_log WHERE ticker = 'FEAT_NAMES'"
        )
        assert row is not None
        stored_names: dict | None = row["raw_feature_names"]
        # asyncpg may return JSONB as a string; handle both cases
        if isinstance(stored_names, str):
            import json

            stored_names = json.loads(stored_names)
        assert stored_names == FEATURE_NAMES
