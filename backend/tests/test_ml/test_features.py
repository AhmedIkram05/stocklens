"""Tests for ml/features.py - technical indicator computation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def simple_close() -> pd.Series:
    """Monotonically increasing close prices (10 days)."""
    return pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])


@pytest.fixture
def volatile_close() -> pd.Series:
    """Close prices with both up and down moves (252 days)."""
    np.random.seed(42)
    returns = np.random.normal(0, 0.02, 252)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.Series(prices)


class TestLogReturns:
    def test_log_returns_positive_trend(self, simple_close: pd.Series) -> None:
        from ml.features import compute_log_returns

        result = compute_log_returns(simple_close)
        assert result["log_ret_1d"].iloc[1] == pytest.approx(np.log(101 / 100), rel=1e-6)
        assert result["log_ret_1d"].isna().iloc[0]
        assert result["log_ret_5d"].isna().iloc[:5].all()

    def test_log_returns_empty(self) -> None:
        from ml.features import compute_log_returns

        result = compute_log_returns(pd.Series([], dtype=float))
        assert len(result) == 0

    def test_log_returns_single_value(self) -> None:
        from ml.features import compute_log_returns

        result = compute_log_returns(pd.Series([100.0]))
        assert result["log_ret_1d"].isna().iloc[0]


class TestMovingAverages:
    def test_sma_basic(self) -> None:
        from ml.features import compute_moving_averages

        close = pd.Series([1, 2, 3, 4, 5, 6])
        result = compute_moving_averages(close, windows=[3])
        assert result["ma_3"].iloc[2] == 2.0
        assert result["ma_3"].iloc[3] == 3.0

    def test_sma_not_enough_data(self) -> None:
        from ml.features import compute_moving_averages

        close = pd.Series([1, 2])
        result = compute_moving_averages(close, windows=[5])
        assert result["ma_5"].isna().all()


class TestRSI:
    def test_rsi_bounds(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_rsi

        rsi = compute_rsi(volatile_close)
        assert rsi.dropna().between(0, 100).all()

    def test_rsi_all_up(self) -> None:
        from ml.features import compute_rsi

        close = pd.Series(np.linspace(100, 200, 30))
        rsi = compute_rsi(close, period=14)
        assert rsi.dropna().iloc[-1] == pytest.approx(100.0, rel=1e-4)

    def test_rsi_all_down(self) -> None:
        from ml.features import compute_rsi

        close = pd.Series(np.linspace(200, 100, 30))
        rsi = compute_rsi(close, period=14)
        assert rsi.dropna().iloc[-1] == pytest.approx(0.0, abs=1e-4)


class TestMACD:
    def test_macd_output_shape(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_macd

        result = compute_macd(volatile_close)
        assert list(result.columns) == ["macd", "macd_signal", "macd_hist"]
        assert len(result) == len(volatile_close)

    def test_macd_zero_for_flat(self) -> None:
        from ml.features import compute_macd

        close = pd.Series([100.0] * 50)
        result = compute_macd(close)
        assert result["macd"].dropna().iloc[-1] == pytest.approx(0.0, abs=1e-6)


class TestRollingVolatility:
    def test_volatility_constant(self) -> None:
        from ml.features import compute_rolling_volatility

        close = pd.Series([100.0] * 50)
        vol = compute_rolling_volatility(close, period=10)
        assert vol.dropna().iloc[-1] == 0.0

    def test_volatility_shape(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_rolling_volatility

        vol = compute_rolling_volatility(volatile_close, period=30)
        assert len(vol) == len(volatile_close)
        assert vol.isna().sum() == 30


class TestStandardise:
    def test_standardise_basic(self) -> None:
        from ml.features import standardise_features

        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]})
        result, means, stds = standardise_features(df)
        assert result["a"].mean() == pytest.approx(0.0, abs=1e-6)
        assert result["a"].std() == pytest.approx(1.0, abs=1e-6)

    def test_standardise_with_inference_means(self) -> None:
        from ml.features import standardise_features

        df_train = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        _, means, stds = standardise_features(df_train)

        df_infer = pd.DataFrame({"a": [6, 7, 8]})
        result, _, _ = standardise_features(df_infer, means, stds)
        expected = (6 - means["a"]) / stds["a"]
        assert result["a"].iloc[0] == pytest.approx(float(expected), abs=1e-6)

    def test_standardise_zero_std(self) -> None:
        from ml.features import standardise_features

        df = pd.DataFrame({"a": [5, 5, 5]})
        result, _, stds = standardise_features(df)
        assert stds["a"] == 1.0
        assert result["a"].iloc[0] == 0.0


class TestAllFeatures:
    def test_compute_all_features(self, volatile_close: pd.Series) -> None:
        from ml.features import compute_all_features

        df = pd.DataFrame({"adjusted_close": volatile_close})
        result = compute_all_features(df)
        expected_cols = [
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
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_compute_all_features_short_series(self) -> None:
        from ml.features import compute_all_features

        df = pd.DataFrame({"adjusted_close": [100.0]})
        result = compute_all_features(df)
        non_macd = [c for c in result.columns if not c.startswith("macd")]
        assert result[non_macd].isna().all().all()
