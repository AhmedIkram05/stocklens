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


def _safe_array(df: pd.DataFrame, col: str, dtype: type = np.float64) -> np.ndarray:
    """Safely extract a column as a numpy array, falling back to NaN if missing."""
    if col in df.columns:
        return df[col].to_numpy(dtype=dtype)
    n = len(df)
    result = np.empty(n, dtype=dtype)
    result.fill(np.nan)
    if dtype == np.int64:
        result.fill(0)
    return result


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 13 V1 technical indicators via the Rust native backend.

    V1 features: log_ret_1/5/21d, ma_5/10/20/50, rsi_14, macd/signal/hist,
    vol_30d, vol_rank.

    The Rust backend produces 19 features total (13 V1 + 6 V2 extras).
    V2 extras (bb_pctb, bb_width, atr_14, obv, williams_r_14, roc_10) are
    dropped after compute — tested multiple times and each one hurts
    performance (turns the model into a single-class predictor).
    """
    feature_cols = [
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
    ]
    close = df["adjusted_close"].to_numpy(dtype=np.float64)
    high = _safe_array(df, "high")
    low = _safe_array(df, "low")
    volume = _safe_array(df, "volume")
    result = _dict_to_df(_rust.compute_all_features(close, high, low, volume), df.index)
    result = result[feature_cols]

    if "ticker" in df.columns:
        result["ticker"] = df["ticker"]
    return result


def compute_cross_sectional_features(
    ticker_features: pd.DataFrame,
    benchmark_features: pd.DataFrame,
) -> pd.DataFrame:
    """Compute excess returns vs benchmark (SPY) for cross-sectional context.

    For each of the three return windows (1d, 5d, 21d), the excess return
    is ticker_return - benchmark_return. These features tell the model
    whether the stock outperformed or underperformed the market — a key
    signal that per-ticker z-scored features alone miss (z-scoring flattens
    market-wide movements).

    Both DataFrames must have the same index (dates). Returns are aligned
    by pandas index matching via reindex() so missing benchmark dates get
    NaN (filled to 0 by the caller).

    Args:
        ticker_features: DataFrame with at least log_ret_1d, log_ret_5d,
            log_ret_21d columns (typically from compute_all_features).
        benchmark_features: Same schema as ticker_features for the
            benchmark index (e.g. SPY).

    Returns:
        DataFrame with columns: excess_ret_1d, excess_ret_5d, excess_ret_21d.
    """
    ret_cols = ["log_ret_1d", "log_ret_5d", "log_ret_21d"]
    excess_cols = ["excess_ret_1d", "excess_ret_5d", "excess_ret_21d"]
    aligned = benchmark_features.reindex(ticker_features.index)
    excess = ticker_features[ret_cols] - aligned[ret_cols]
    excess.columns = excess_cols
    return excess


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
