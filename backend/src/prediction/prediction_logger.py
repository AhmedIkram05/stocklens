"""
Prediction logger — fire-and-forget logging of prediction requests for drift monitoring.

Logs run in a background thread pool so the prediction endpoint is never blocked.
Uses the existing connection pool via connection_ctx() — avoids pool exhaustion
because the thread pool limits concurrent DB connections to max_workers (2).
"""

from __future__ import annotations

import asyncio
import json
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

# Capture the running event loop at import time so thread-pool callbacks can
# schedule coroutines on it via run_coroutine_threadsafe.  Without this the
# asyncpg pool cannot be shared across event loops and logs fail silently.
try:
    _main_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
except RuntimeError:
    _main_loop = None


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
    """Synchronous wrapper for log_prediction. Runs the coroutine in a new event loop.

    This is called from the thread pool executor.
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
            asyncio.run(
                _log_prediction(
                    ticker=ticker,
                    model_version=model_version,
                    prediction=prediction,
                    confidence=confidence,
                    probabilities=probabilities,
                    feature_values=feature_values,
                    feature_window=feature_window,
                )
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
