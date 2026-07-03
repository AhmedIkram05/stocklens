"""
Adaptive labeling for directional forecasting.

Labels are computed per-ticker using a rolling volatility threshold,
normalising across tickers with different base volatility levels.

Label definitions:
    FLAT  if |log_return| < 0.5 * sigma_30d
    UP    if log_return >= 0.5 * sigma_30d
    DOWN  if log_return <= -0.5 * sigma_30d
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_adaptive_labels(
    close: pd.Series,
    vol_lookback: int = 30,
    threshold_mult: float = 0.5,
    forecast_horizon: int = 1,
) -> pd.Series:
    """Compute UP/FLAT/DOWN labels using adaptive volatility threshold.

    Args:
        close: Adjusted close prices (pandas Series).
        vol_lookback: Window for rolling volatility calculation.
        threshold_mult: Multiplier on sigma for the FLAT band.
        forecast_horizon: Days ahead to predict (default 1).

    Returns:
        Series with labels: 0=DOWN, 1=FLAT, 2=UP. NaN for last horizon+
        rows where future return is unavailable.
    """
    forward_ret = np.log(close.shift(-forecast_horizon) / close)

    daily_log_ret = np.log(close / close.shift(1))
    rolling_vol = daily_log_ret.rolling(window=vol_lookback).std()

    threshold = rolling_vol * threshold_mult

    labels = pd.Series(index=close.index, dtype=float)
    labels[forward_ret.abs() < threshold] = 1.0  # FLAT
    labels[forward_ret >= threshold] = 2.0  # UP
    labels[forward_ret <= -threshold] = 0.0  # DOWN

    labels[forward_ret.isna() | threshold.isna()] = np.nan

    return labels


def compute_label_distribution(labels: pd.Series) -> dict[str, float]:
    """Compute class distribution of labels.

    Returns:
        Dict mapping class name to proportion (0-1).
    """
    valid = labels.dropna()
    if len(valid) == 0:
        return {"DOWN": 0.0, "FLAT": 0.0, "UP": 0.0}

    total = len(valid)
    return {
        "DOWN": float((valid == 0).sum() / total),
        "FLAT": float((valid == 1).sum() / total),
        "UP": float((valid == 2).sum() / total),
    }
