"""
Prediction logger — fire-and-forget logging of prediction requests for drift monitoring.

Logs run in a background thread pool so the prediction endpoint is never blocked.
Uses the existing connection pool via connection_ctx() — avoids pool exhaustion
because the thread pool limits concurrent DB connections to max_workers (2).
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from src.config import settings

logger = structlog.get_logger()

# Feature names — must match the order produced by prediction_service._compute_features
# 17 features: 13 V1 + vol_pct + 3 cross-sectional
FEATURE_NAMES = [
    "log_ret_1d",
    "log_ret_5d",
    "log_ret_21d",
    "ma_5",
    "ma_10",
    "ma_20",
    "ma_50",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "vol_30d",
    "vol_rank",
    "vol_pct",
    "excess_ret_1d",
    "excess_ret_5d",
    "excess_ret_21d",
]

# Thread pool for fire-and-forget logging — max_workers=2 limits DB connection pressure
_logger_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pred_log")

# The event loop that owns the asyncpg pool. Captured from the app lifespan
# via set_main_loop() — NOT at import time, which ran before any loop existed
# under pytest/scripts/gunicorn-preload and silently lost every log to a
# foreign-loop RuntimeError.
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Record the running event loop so worker threads can schedule DB writes on it.

    Called from the FastAPI lifespan (startup), where the loop that owns the
    asyncpg connection pool is running.
    """
    global _main_loop
    _main_loop = loop


# Bound the fire-and-forget backlog: a DB slowdown must not grow the executor
# queue without limit (and shutdown would drop everything pending anyway).
_MAX_PENDING_LOGS = 1000
_pending_slots = threading.BoundedSemaphore(_MAX_PENDING_LOGS)


def submit_prediction_log(*args: Any) -> None:
    """Queue log_prediction_sync on the logger executor, dropping when saturated.

    The permit is released from the submitted future's done-callback — not from
    the task body — so a task that is cancelled before it runs (executor
    shutdown) or an executor that never runs it cannot leak a slot and slowly
    wedge the bounded queue shut.
    """
    if not _pending_slots.acquire(blocking=False):
        logger.warning("prediction_log_dropped", reason="pending_queue_full")
        return

    try:
        future = _logger_executor.submit(log_prediction_sync, *args)
    except RuntimeError:
        # Executor already shut down — nothing was queued.
        _pending_slots.release()
        logger.warning("prediction_log_dropped", reason="executor_shutdown")
        return

    future.add_done_callback(lambda _f: _pending_slots.release())


def _is_nan(val: float) -> bool:
    """True if *val* is NaN (handles both float('nan') and np.float64)."""
    try:
        return bool(np.isnan(val))
    except TypeError:
        return False


def log_prediction_sync(
    ticker: str,
    model_version: str,
    prediction: str,
    confidence: float,
    probabilities: dict[str, float],
    feature_values: np.ndarray | None,
    feature_window: np.ndarray | None,
) -> None:
    """Synchronous wrapper for log_prediction, called from the thread pool.

    Schedules the coroutine on the lifespan-captured event loop (the one that
    owns the asyncpg pool). With no such loop the write is dropped with a
    warning rather than run on a foreign loop.
    """
    try:
        if _main_loop is not None and _main_loop.is_running():
            # Schedule on the captured main event loop so the asyncpg pool
            # (bound to that loop) can be used.
            asyncio.run_coroutine_threadsafe(
                _log_prediction(
                    ticker=ticker,
                    model_version=model_version,
                    prediction=prediction,
                    confidence=confidence,
                    probabilities=probabilities,
                    feature_values=feature_values,
                    feature_window=feature_window,
                ),
                _main_loop,
            )
        else:
            # No lifespan-captured loop (pytest, scripts, gunicorn preload).
            # A throwaway asyncio.run() here would write on a foreign loop —
            # the asyncpg pool belongs to _main_loop, so the write cannot
            # succeed — and, worse, it runs inline on the executor thread and
            # blocks it; a stalled DB op then wedges interpreter shutdown.
            # Drop it and make the loss visible (never block the endpoint).
            logger.warning(
                "prediction_log_dropped",
                reason="no_main_loop",
                ticker=ticker,
                hint="call set_main_loop() from the app lifespan",
            )
    except Exception as exc:
        logger.warning("prediction_log_sync_failed", ticker=ticker, error=str(exc))


async def _log_prediction(
    ticker: str,
    model_version: str,
    prediction: str,
    confidence: float,
    probabilities: dict[str, float],
    feature_values: np.ndarray | None,  # (T, 17) full feature window, pre-window
    feature_window: np.ndarray | None,  # (30, 17) the actual model input
) -> None:
    """Log a single prediction to the prediction_log table.

    This is fire-and-forget: errors are logged but never propagated to the
    caller. The prediction response has already been sent.
    """
    if not settings.PREDICTION_LOG_ENABLED:
        return

    if feature_values is not None:
        # raw_features intentionally omitted — only feature_stats logged
        means = [float(v) for v in np.nanmean(feature_values, axis=0).tolist()]
        stds = [float(v) for v in np.nanstd(feature_values, axis=0).tolist()]
        feature_stats = {
            "means": [None if _is_nan(v) else v for v in means],
            "stds": [None if _is_nan(v) else v for v in stds],
            "n_samples": int(feature_values.shape[0]),
        }
    else:
        feature_stats = None

    if feature_window is not None:
        window_features = feature_window.tolist()  # (30, 17)
    else:
        window_features = None

    # Build the features JSONB — store both the raw window and stats
    features_payload: dict[str, Any] = {
        "window": window_features,
        "stats": feature_stats,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    raw_names_payload = FEATURE_NAMES

    try:
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            await conn.execute(
                """
                INSERT INTO prediction_log
                    (ticker, model_version, prediction, confidence, probabilities,
                     features, feature_stats, raw_feature_names)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb)
                """,
                ticker.upper(),
                model_version,
                prediction,
                confidence,
                json.dumps(probabilities),
                json.dumps(features_payload),
                json.dumps(feature_stats) if feature_stats else None,
                json.dumps(raw_names_payload),
            )
    except Exception as exc:
        # Log but never raise — the prediction response has already been sent
        logger.warning("prediction_log_failed", ticker=ticker, error=str(exc))


def compute_feature_stats(feature_values: np.ndarray | None) -> dict | None:
    """Compute per-feature statistics from the raw feature matrix.

    Returns None if feature_values is None or empty.
    """
    if feature_values is None or feature_values.size == 0:
        return None
    means = [float(v) for v in np.nanmean(feature_values, axis=0).tolist()]
    stds = [float(v) for v in np.nanstd(feature_values, axis=0).tolist()]
    return {
        "means": [None if _is_nan(v) else v for v in means],
        "stds": [None if _is_nan(v) else v for v in stds],
        "n_samples": int(feature_values.shape[0]),
    }
