"""
Technical indicator computation — Rust-native backend.

All public functions accept/return pandas objects for seamless API compatibility.
``standardise_features`` is kept in Python (numpy-broadcast O(n), no Rust gain).
"""

from __future__ import annotations

import features_engine as _rust
import numpy as np
import pandas as pd


def _arr_to_series(arr: np.ndarray, index: pd.Index) -> pd.Series:
    return pd.Series(arr, index=index)


def _dict_to_df(data: dict[str, np.ndarray], index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {k: _arr_to_series(v, index) for k, v in data.items()},
        index=index,
    )


def compute_log_returns(close: pd.Series, periods: list[int] | None = None) -> pd.DataFrame:
    if periods is None:
        periods = [1, 5, 21]
    return _dict_to_df(
        _rust.compute_log_returns(close.to_numpy(dtype=np.float64), periods),
        close.index,
    )


def compute_moving_averages(close: pd.Series, windows: list[int] | None = None) -> pd.DataFrame:
    if windows is None:
        windows = [5, 10, 20, 50]
    return _dict_to_df(
        _rust.compute_moving_averages(close.to_numpy(dtype=np.float64), windows),
        close.index,
    )


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    return _arr_to_series(
        _rust.compute_rsi(close.to_numpy(dtype=np.float64), period),
        close.index,
    )


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    return _dict_to_df(
        _rust.compute_macd(close.to_numpy(dtype=np.float64), fast, slow, signal),
        close.index,
    )


def compute_rolling_volatility(close: pd.Series, period: int = 30) -> pd.Series:
    return _arr_to_series(
        _rust.compute_rolling_volatility(close.to_numpy(dtype=np.float64), period),
        close.index,
    )


def compute_volatility_rank(close: pd.Series, period: int = 252) -> pd.Series:
    return _arr_to_series(
        _rust.compute_volatility_rank(close.to_numpy(dtype=np.float64), period),
        close.index,
    )


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 13 technical indicators via the Rust native backend."""
    close = df["adjusted_close"].to_numpy(dtype=np.float64)
    result = _dict_to_df(_rust.compute_all_features(close), df.index)
    if "ticker" in df.columns:
        result["ticker"] = df["ticker"]
    return result


def standardise_features(
    df: pd.DataFrame,
    means: pd.Series | None = None,
    stds: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Z-score standardise all feature columns.

    For training: pass means=None, stds=None to compute from data.
    For inference: pass the training means and stds.

    Returns:
        (standardised_df, means, stds) tuple.
    """
    feature_cols = [c for c in df.columns if not c.startswith("label") and c != "ticker"]
    if means is None or stds is None:
        computed_means = df[feature_cols].mean()
        computed_stds = df[feature_cols].std().replace(0, 1.0)
        means = means if means is not None else computed_means
        stds = stds if stds is not None else computed_stds

    result = df.copy()
    result[feature_cols] = (df[feature_cols] - means) / stds
    return result, means, stds
