#!/usr/bin/env python3
"""Equivalence harness: compare Rust-native output against pure Python reference.

Generates random price data, computes all 13 indicators with both backends,
and asserts near-identity. Python reference is inlined here so the harness
is self-contained.
"""

from __future__ import annotations

import features_engine as rust_mod
import numpy as np
import pandas as pd

TOLERANCE = 1e-10


# ── Inlined Python reference implementation ──────────────────────────────


def _py_log_returns(close: pd.Series, periods: list[int]) -> pd.DataFrame:
    data = {}
    for p in periods:
        data[f"log_ret_{p}d"] = close.pct_change().pipe(lambda s: s.rename(None))  # placeholder
    vals = close.to_numpy(dtype=np.float64)
    data = {}
    for p in periods:
        col = f"log_ret_{p}d"
        shifted = np.full_like(vals, np.nan)
        if len(vals) > p:
            shifted[p:] = np.log(vals[p:] / vals[:-p])
        data[col] = shifted
    return pd.DataFrame(data, index=close.index)


def _py_moving_averages(close: pd.Series, windows: list[int]) -> pd.DataFrame:
    vals = close.to_numpy(dtype=np.float64)
    data = {}
    for w in windows:
        col = f"ma_{w}"
        sma = np.full_like(vals, np.nan)
        if len(vals) >= w:
            cumsum = np.cumsum(vals)
            cumsum[w - 1 :] = cumsum[w - 1 :] - np.concatenate([[0], cumsum[:-w]])
            sma[w - 1 :] = cumsum[w - 1 :] / w
        data[col] = sma
    return pd.DataFrame(data, index=close.index)


def _py_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    vals = close.to_numpy(dtype=np.float64)
    n = len(vals)
    result = np.full(n, np.nan)
    if n <= period + 1:
        return pd.Series(result, index=close.index)
    gains = np.maximum(np.diff(vals), 0)
    losses = np.maximum(-np.diff(vals), 0)
    sum_gain = gains[:period].sum()
    sum_loss = losses[:period].sum()
    for i in range(period, n):
        if i > period:
            sum_gain += gains[i - 1] - gains[i - 1 - period]
            sum_loss += losses[i - 1] - losses[i - 1 - period]
        avg_gain = sum_gain / period
        avg_loss = sum_loss / period
        if avg_loss != 0:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))
        else:
            result[i] = 100.0
    return pd.Series(result, index=close.index)


def _py_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    vals = close.to_numpy(dtype=np.float64)
    n = len(vals)

    def _ema(arr: np.ndarray, span: int) -> np.ndarray:
        out = np.full(n, np.nan)
        if n < span:
            return out
        alpha = 2.0 / (span + 1.0)
        out[span - 1] = arr[:span].mean()
        for i in range(span, n):
            out[i] = (arr[i] - out[i - 1]) * alpha + out[i - 1]
        return out

    ema_fast = _ema(vals, fast)
    ema_slow = _ema(vals, slow)
    macd_line = ema_fast - ema_slow
    macd_signal = _ema(macd_line, signal)
    macd_hist = macd_line - macd_signal
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist},
        index=close.index,
    )


def _py_rolling_volatility(close: pd.Series, period: int = 30) -> pd.Series:
    vals = close.to_numpy(dtype=np.float64)
    n = len(vals)
    result = np.full(n, np.nan)
    if n < 2:
        return pd.Series(result, index=close.index)
    log_rets = np.full(n, np.nan)
    log_rets[1:] = np.log(vals[1:] / vals[:-1])
    if n < period + 1:
        return pd.Series(result, index=close.index)
    ddof = period - 1
    sum_ = log_rets[1 : period + 1].sum()
    sum_sq = (log_rets[1 : period + 1] ** 2).sum()
    mean = sum_ / period
    var = ((sum_sq / period) - mean**2) * period / ddof
    result[period] = np.sqrt(var) if var > 0 else 0.0
    for i in range(period + 1, n):
        sum_ += log_rets[i] - log_rets[i - period]
        sum_sq += log_rets[i] ** 2 - log_rets[i - period] ** 2
        mean = sum_ / period
        var = ((sum_sq / period) - mean**2) * period / ddof
        result[i] = np.sqrt(var) if var > 0 else 0.0
    return pd.Series(result, index=close.index)


def _py_volatility_rank(close: pd.Series, period: int = 252) -> pd.Series:
    vol = _py_rolling_volatility(close, 30).to_numpy(dtype=np.float64)
    n = len(vol)
    result = np.full(n, np.nan)
    if n <= period:
        return pd.Series(result, index=close.index)
    for i in range(period, n):
        current = vol[i]
        if np.isnan(current):
            continue
        window = vol[i - (period - 1) : i + 1]
        count_le = np.sum(window <= current)
        result[i] = count_le / period
    return pd.Series(result, index=close.index)


def _py_compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["adjusted_close"]
    parts = [
        _py_log_returns(close, [1, 5, 21]),
        _py_moving_averages(close, [5, 10, 20, 50]),
        _py_rsi(close, 14).to_frame("rsi_14"),
        _py_macd(close, 12, 26, 9),
        _py_rolling_volatility(close, 30).to_frame("vol_30d"),
        _py_volatility_rank(close, 252).to_frame("vol_rank"),
    ]
    result = pd.concat(parts, axis=1)
    if "ticker" in df.columns:
        result["ticker"] = df["ticker"]
    return result


# ── Equivalence test ─────────────────────────────────────────────────────


def _generate_prices(n: int = 2000, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, 0.02, n)
    return pd.Series(100 * np.exp(np.cumsum(returns)))


def test_equivalence() -> None:
    close = _generate_prices()

    # Rust backend
    raw = rust_mod.compute_all_features(close.to_numpy(dtype=np.float64))
    rust_out = {k: pd.Series(v, index=close.index) for k, v in raw.items()}

    # Python reference (inlined)
    df = pd.DataFrame({"adjusted_close": close})
    py_result = _py_compute_all_features(df)
    py_out = {c: py_result[c] for c in py_result.columns if c != "ticker"}

    mismatches = []
    for col in rust_out:
        if col not in py_out:
            mismatches.append(f"Column {col!r} missing from Python output")
            continue
        r_arr = rust_out[col].to_numpy(dtype=np.float64)
        p_arr = py_out[col].to_numpy(dtype=np.float64)
        both_nan = np.isnan(r_arr) & np.isnan(p_arr)
        diff = np.where(both_nan, 0.0, np.abs(r_arr - p_arr))
        max_diff = diff.max()
        if max_diff > TOLERANCE:
            bad_idx = int(np.argmax(diff))
            mismatches.append(
                f"{col}: max_diff={max_diff:.2e} at index {bad_idx} "
                f"(rust={r_arr[bad_idx]:.10f}, py={p_arr[bad_idx]:.10f})"
            )

    if mismatches:
        for m in mismatches:
            print(f"  MISMATCH: {m}")
        msg = f"{len(mismatches)} column(s) deviate beyond {TOLERANCE}"
        raise AssertionError(msg)
    print(f"OK — all {len(rust_out)} columns equivalent within {TOLERANCE}")


def main() -> None:
    test_equivalence()


if __name__ == "__main__":
    main()
