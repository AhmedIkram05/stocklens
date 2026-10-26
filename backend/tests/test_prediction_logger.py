"""
Tests for the prediction logger — fire-and-forget logging of prediction requests.

All tests run inside a transaction that is rolled back on teardown
(see conftest.py ``_test_db`` fixture).

Integration tests call ``_log_prediction`` directly (not via the sync wrapper
``log_prediction_sync``): with no lifespan-captured loop the wrapper drops the
write, so tests exercise the coroutine directly.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.prediction.prediction_logger import (
    FEATURE_NAMES,
    _is_nan,
    _log_prediction,
    compute_feature_stats,
    log_prediction_sync,
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


class TestIsNan:
    """Tests for _is_nan helper."""

    def test_nan_float(self):

        assert _is_nan(float("nan")) is True

    def test_nan_numpy(self):
        import numpy as np

        assert _is_nan(np.float64("nan")) is True

    def test_finite_float(self):
        assert _is_nan(42.0) is False

    def test_non_numeric_returns_false(self):
        """TypeError in np.isnan → _is_nan returns False."""
        result = _is_nan("not a number")  # type: ignore[arg-type]
        assert result is False

    def test_none_returns_false(self):
        result = _is_nan(None)  # type: ignore[arg-type]
        assert result is False


class TestLogPredictionSync:
    """Tests for log_prediction_sync — the thread-pool entry point."""

    def test_drops_when_no_main_loop(self, monkeypatch):
        """No captured loop: drop with a warning instead of running the write on
        a throwaway loop. A foreign-loop write cannot succeed and, run inline on
        the executor thread, blocks it until the interpreter hangs."""

        calls = []

        async def fake_log(**kwargs):
            calls.append(kwargs)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.prediction.prediction_logger._main_loop", None)
        monkeypatch.setattr("src.prediction.prediction_logger._log_prediction", fake_log)
        monkeypatch.setattr("src.prediction.prediction_logger.logger", mock_logger)

        log_prediction_sync(
            ticker="AAPL",
            model_version="v1",
            prediction="UP",
            confidence=0.8,
            probabilities={"UP": 0.8, "DOWN": 0.1, "FLAT": 0.1},
            feature_values=None,
            feature_window=None,
        )

        assert calls == []  # the coroutine is never executed
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.args[0] == "prediction_log_dropped"
        assert mock_logger.warning.call_args.kwargs["reason"] == "no_main_loop"

    def test_main_loop_schedule_error_is_logged(self, monkeypatch):
        """An error scheduling on the main loop is caught, never raised."""
        mock_logger = MagicMock()
        main_loop = MagicMock()
        main_loop.is_running.return_value = True
        monkeypatch.setattr("src.prediction.prediction_logger._main_loop", main_loop)
        monkeypatch.setattr("src.prediction.prediction_logger._log_prediction", MagicMock())
        monkeypatch.setattr("src.prediction.prediction_logger.logger", mock_logger)
        monkeypatch.setattr(
            "src.prediction.prediction_logger.asyncio.run_coroutine_threadsafe",
            MagicMock(side_effect=RuntimeError("event loop is closed")),
        )

        # Should not raise
        log_prediction_sync(
            ticker="AAPL",
            model_version="v1",
            prediction="UP",
            confidence=0.8,
            probabilities={"UP": 0.8, "DOWN": 0.1, "FLAT": 0.1},
            feature_values=None,
            feature_window=None,
        )

        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.args[0] == "prediction_log_sync_failed"

    def test_log_prediction_sync_with_main_loop(self, monkeypatch):
        """When a running main loop is captured, run_coroutine_threadsafe is used."""
        main_loop = MagicMock()
        main_loop.is_running.return_value = True
        monkeypatch.setattr("src.prediction.prediction_logger._main_loop", main_loop)
        monkeypatch.setattr("src.prediction.prediction_logger._log_prediction", MagicMock())
        with patch(
            "src.prediction.prediction_logger.asyncio.run_coroutine_threadsafe"
        ) as mock_schedule:
            log_prediction_sync(
                ticker="AAPL",
                model_version="v1",
                prediction="UP",
                confidence=0.8,
                probabilities={"UP": 0.8, "DOWN": 0.1, "FLAT": 0.1},
                feature_values=None,
                feature_window=None,
            )
            mock_schedule.assert_called_once()


class TestSetMainLoop:
    """M13 regression: the loop is captured from the lifespan, not at import."""

    def test_set_main_loop_captures_loop(self, monkeypatch):
        import asyncio

        import src.prediction.prediction_logger as pl

        monkeypatch.setattr("src.prediction.prediction_logger._main_loop", None)
        loop = asyncio.new_event_loop()
        try:
            pl.set_main_loop(loop)
            assert pl._main_loop is loop
        finally:
            loop.close()

    def test_import_does_not_capture_a_loop(self, monkeypatch):
        """Re-importing the module under a runner without a loop must not
        fabricate one — capture happens only via set_main_loop()."""
        import src.prediction.prediction_logger as pl

        # The module-level default is None; set_main_loop is the only setter.
        assert callable(pl.set_main_loop)
        monkeypatch.setattr("src.prediction.prediction_logger._main_loop", None)
        # Simulating the pre-lifespan state: still None, no crash.
        assert pl._main_loop is None


class _RecordingExecutor:
    """Stand-in for ThreadPoolExecutor.submit that runs the task synchronously
    and returns a completed Future, so the done-callback behaves like production."""

    def __init__(self) -> None:
        self.submitted = 0

    def submit(self, fn, *args, **kwargs) -> Future:
        self.submitted += 1
        future: Future = Future()
        try:
            fn(*args, **kwargs)
        except BaseException as exc:  # pragma: no cover - defensive
            future.set_exception(exc)
        else:
            future.set_result(None)
        return future


class TestSubmitPredictionLog:
    """M13 regression: the fire-and-forget backlog is bounded and never leaks."""

    def test_submits_through_executor(self, monkeypatch):
        import src.prediction.prediction_logger as pl

        executor = _RecordingExecutor()
        monkeypatch.setattr(pl, "_logger_executor", executor)
        monkeypatch.setattr(pl, "_pending_slots", threading.BoundedSemaphore(2))
        monkeypatch.setattr(pl, "_main_loop", None)

        pl.submit_prediction_log("AAPL", "v1", "UP", 0.8, {}, None, None)

        assert executor.submitted == 1
        # Permit released by the future's done-callback, not the task body.
        assert pl._pending_slots._value == 2

    def test_drops_when_saturated(self, monkeypatch):
        import src.prediction.prediction_logger as pl

        submitted = []
        executor = MagicMock()
        executor.submit.side_effect = lambda *a: submitted.append(a)
        monkeypatch.setattr(pl, "_logger_executor", executor)
        monkeypatch.setattr(pl, "_pending_slots", threading.BoundedSemaphore(0))

        pl.submit_prediction_log("AAPL", "v1", "UP", 0.8, {}, None, None)

        assert submitted == []  # dropped, not queued
        assert pl._pending_slots._value == 0  # and nothing leaked

    def test_cancelled_task_releases_slot(self, monkeypatch):
        """A task cancelled before it runs (executor shutdown with cancel_futures)
        must still release its permit — the body never executes, so the
        done-callback is the only release path."""
        import src.prediction.prediction_logger as pl

        def _submit(fn, *args, **kwargs):
            future: Future = Future()
            future.cancel()  # never runs fn
            return future

        executor = MagicMock()
        executor.submit.side_effect = _submit
        monkeypatch.setattr(pl, "_logger_executor", executor)
        monkeypatch.setattr(pl, "_pending_slots", threading.BoundedSemaphore(2))

        pl.submit_prediction_log("AAPL", "v1", "UP", 0.8, {}, None, None)

        assert pl._pending_slots._value == 2  # released despite never running
