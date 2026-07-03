"""
Technical indicator computation from OHLCV data.

All functions are pure (no DB, no IO) and operate on numpy arrays or
pandas DataFrames. Every function handles NaN/inf edge cases.

Returns a DataFrame with one row per trading day and columns for each feature.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_log_returns(close: pd.Series, periods: list[int] = [1, 5, 21]) -> pd.DataFrame:
    """Compute multi-period log returns from adjusted close prices.

    Args:
        close: Adjusted close prices (pandas Series, index = date).
        periods: Lookback periods in trading days.

    Returns:
        DataFrame with columns log_ret_1d, log_ret_5d, log_ret_21d.
    """
    result = pd.DataFrame(index=close.index)
    for p in periods:
        col = f"log_ret_{p}d"
        result[col] = np.log(close / close.shift(p))
    return result


def compute_moving_averages(close: pd.Series, windows: list[int] = [5, 10, 20, 50]) -> pd.DataFrame:
    """Compute simple moving averages.

    Returns:
        DataFrame with columns ma_5, ma_10, ma_20, ma_50.
    """
    result = pd.DataFrame(index=close.index)
    for w in windows:
        result[f"ma_{w}"] = close.rolling(window=w).mean()
    return result


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index (RSI).

    Uses Wilder's smoothed method (simple moving average of gains/losses).

    Returns:
        Series with RSI values (0-100), NaN for first `period` rows.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Compute MACD (Moving Average Convergence Divergence).

    Returns:
        DataFrame with columns macd, macd_signal, macd_hist.
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal_line

    return pd.DataFrame(
        {
            "macd": macd_line,
            "macd_signal": macd_signal_line,
            "macd_hist": macd_hist,
        },
        index=close.index,
    )


def compute_rolling_volatility(close: pd.Series, period: int = 30) -> pd.Series:
    """Compute rolling standard deviation of daily log returns.

    Returns:
        Series with rolling volatility values.
    """
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window=period).std()


def compute_volatility_rank(close: pd.Series, period: int = 252) -> pd.Series:
    """Compute the percentile rank of current volatility within a 1-year window.

    Returns:
        Series with percentile ranks (0-1), NaN for first `period` rows.
    """
    vol = compute_rolling_volatility(close, period=30)
    rank = vol.rolling(window=period, min_periods=period).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 0 else np.nan,
        raw=False,
    )
    return rank


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


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 13 technical indicators from OHLCV data.

    Args:
        df: DataFrame with columns: date, adjusted_close (at minimum).

    Returns:
        DataFrame with date index and 13 feature columns plus ticker column.
    """
    close = df["adjusted_close"].copy()

    features = pd.DataFrame(index=df.index)

    for col, series in compute_log_returns(close).items():
        features[col] = series

    for col, series in compute_moving_averages(close).items():
        features[col] = series

    features["rsi_14"] = compute_rsi(close)

    macd_df = compute_macd(close)
    features["macd"] = macd_df["macd"]
    features["macd_signal"] = macd_df["macd_signal"]
    features["macd_hist"] = macd_df["macd_hist"]

    features["vol_30d"] = compute_rolling_volatility(close)
    features["vol_rank"] = compute_volatility_rank(close)

    if "ticker" in df.columns:
        features["ticker"] = df["ticker"]

    return features
