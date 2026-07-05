"""
Adaptive labeling for directional forecasting.

Labels are computed per-ticker using a rolling volatility threshold,
normalising across tickers with different base volatility levels.

The threshold is: rolling_vol * threshold_mult * sqrt(forecast_horizon)

With threshold_mult=0.7 and forecast_horizon=5 (ML_CONFIG defaults):
    FLAT  if |log_return| < 1.57 * sigma_30d  (~52% of samples)
    UP    if log_return >= 1.57 * sigma_30d     (~24% of samples)
    DOWN  if log_return <= -1.57 * sigma_30d    (~24% of samples)

The widened FLAT band (was 0.671σ at mult=0.3) ensures directional labels
reflect stronger, higher-confidence moves with better signal-to-noise ratio.
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

    # Scale threshold by sqrt(forecast_horizon) — multi-day return volatility
    # grows with sqrt(N), so the FLAT band needs to widen to keep the same
    # effective class balance.
    threshold = rolling_vol * threshold_mult * np.sqrt(forecast_horizon)

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
