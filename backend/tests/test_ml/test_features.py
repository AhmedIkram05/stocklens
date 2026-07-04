"""Tests for Rust-native feature computation."""

from __future__ import annotations

import features_engine as _rust
import numpy as np
import pandas as pd
import pytest


def _impl():
    """Return an adapter wrapping the raw Rust module."""

    class _RustAdapter:
        """Wraps raw Rust function calls into the same signature as the Python API."""

        def compute_log_returns(
            self, close: pd.Series, periods: list[int] | None = None
        ) -> pd.DataFrame:
            if periods is None:
                periods = [1, 5, 21]
            raw = _rust.compute_log_returns(close.to_numpy(dtype=np.float64), periods)
            return pd.DataFrame(raw, index=close.index)

        def compute_moving_averages(
            self, close: pd.Series, windows: list[int] | None = None
        ) -> pd.DataFrame:
            if windows is None:
                windows = [5, 10, 20, 50]
            raw = _rust.compute_moving_averages(close.to_numpy(dtype=np.float64), windows)
            return pd.DataFrame(raw, index=close.index)

        def compute_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
            raw = _rust.compute_rsi(close.to_numpy(dtype=np.float64), period)
            return pd.Series(raw.astype(float), index=close.index)

        def compute_macd(
            self,
            close: pd.Series,
            fast: int = 12,
            slow: int = 26,
            signal: int = 9,
        ) -> pd.DataFrame:
            raw = _rust.compute_macd(close.to_numpy(dtype=np.float64), fast, slow, signal)
            return pd.DataFrame(raw, index=close.index)

        def compute_rolling_volatility(self, close: pd.Series, period: int = 30) -> pd.Series:
            raw = _rust.compute_rolling_volatility(close.to_numpy(dtype=np.float64), period)
            return pd.Series(raw.astype(float), index=close.index)

        def compute_volatility_rank(self, close: pd.Series, period: int = 252) -> pd.Series:
            raw = _rust.compute_volatility_rank(close.to_numpy(dtype=np.float64), period)
            return pd.Series(raw.astype(float), index=close.index)

        def compute_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
            close = df["adjusted_close"].to_numpy(dtype=np.float64)
            raw = _rust.compute_all_features(close)
            result = pd.DataFrame(raw, index=df.index)
            if "ticker" in df.columns:
                result["ticker"] = df["ticker"]
            return result

    return _RustAdapter()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLogReturns:
    def test_log_returns_positive_trend(self, simple_close: pd.Series) -> None:
        impl = _impl()
        result = impl.compute_log_returns(simple_close)
        assert result["log_ret_1d"].iloc[1] == pytest.approx(np.log(101 / 100), rel=1e-6)
        assert result["log_ret_1d"].isna().iloc[0]
        assert result["log_ret_5d"].isna().iloc[:5].all()

    def test_log_returns_empty(self) -> None:
        impl = _impl()
        result = impl.compute_log_returns(pd.Series([], dtype=float))
        assert len(result) == 0

    def test_log_returns_single_value(self) -> None:
        impl = _impl()
        result = impl.compute_log_returns(pd.Series([100.0]))
        assert result["log_ret_1d"].isna().iloc[0]


class TestMovingAverages:
    def test_sma_basic(self) -> None:
        impl = _impl()
        close = pd.Series([1, 2, 3, 4, 5, 6])
        result = impl.compute_moving_averages(close, windows=[3])
        assert result["ma_3"].iloc[2] == 2.0
        assert result["ma_3"].iloc[3] == 3.0

    def test_sma_not_enough_data(self) -> None:
        impl = _impl()
        close = pd.Series([1, 2])
        result = impl.compute_moving_averages(close, windows=[5])
        assert result["ma_5"].isna().all()


class TestRSI:
    def test_rsi_bounds(self, volatile_close: pd.Series) -> None:
        impl = _impl()
        rsi = impl.compute_rsi(volatile_close)
        assert rsi.dropna().between(0, 100).all()

    def test_rsi_all_up(self) -> None:
        impl = _impl()
        close = pd.Series(np.linspace(100, 200, 30))
        rsi = impl.compute_rsi(close, period=14)
        assert rsi.dropna().iloc[-1] == pytest.approx(100.0, rel=1e-4)

    def test_rsi_all_down(self) -> None:
        impl = _impl()
        close = pd.Series(np.linspace(200, 100, 30))
        rsi = impl.compute_rsi(close, period=14)
        assert rsi.dropna().iloc[-1] == pytest.approx(0.0, abs=1e-4)


class TestMACD:
    def test_macd_output_shape(self, volatile_close: pd.Series) -> None:
        impl = _impl()
        result = impl.compute_macd(volatile_close)
        assert list(result.columns) == ["macd", "macd_signal", "macd_hist"]
        assert len(result) == len(volatile_close)

    def test_macd_zero_for_flat(self) -> None:
        impl = _impl()
        close = pd.Series([100.0] * 50)
        result = impl.compute_macd(close)
        assert result["macd"].dropna().iloc[-1] == pytest.approx(0.0, abs=1e-6)


class TestRollingVolatility:
    def test_volatility_constant(self) -> None:
        impl = _impl()
        close = pd.Series([100.0] * 50)
        vol = impl.compute_rolling_volatility(close, period=10)
        assert vol.dropna().iloc[-1] == 0.0

    def test_volatility_shape(self, volatile_close: pd.Series) -> None:
        impl = _impl()
        vol = impl.compute_rolling_volatility(volatile_close, period=30)
        assert len(vol) == len(volatile_close)
        assert vol.isna().sum() == 30


class TestStandardise:
    """standardise_features is pure Python — no Rust equivalent."""

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
        impl = _impl()
        df = pd.DataFrame({"adjusted_close": volatile_close})
        result = impl.compute_all_features(df)
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
        impl = _impl()
        df = pd.DataFrame({"adjusted_close": [100.0]})
        result = impl.compute_all_features(df)
        non_macd = [c for c in result.columns if not c.startswith("macd")]
        assert result[non_macd].isna().all().all()


# ---------------------------------------------------------------------------
# Production-shim integration tests (exercises features.py directly)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("features_engine"),
    reason="Rust native module not installed",
)
class TestFeaturesShim:
    """Exercises the production ``ml.features`` module — the same code path
    used at runtime.  Catches regressions in the ``_arr_to_series`` /
    ``_dict_to_df`` bridge."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        import ml.features as _mod  # noqa: PLC0415  — late import for skip checks

        self.mod = _mod

    def test_compute_rsi_returns_series(self, volatile_close: pd.Series) -> None:
        result = self.mod.compute_rsi(volatile_close, period=14)
        assert isinstance(result, pd.Series)
        pd.testing.assert_index_equal(result.index, volatile_close.index)

    def test_compute_macd_returns_dataframe(self, volatile_close: pd.Series) -> None:
        result = self.mod.compute_macd(volatile_close)
        assert isinstance(result, pd.DataFrame)
        pd.testing.assert_index_equal(result.index, volatile_close.index)
        assert list(result.columns) == ["macd", "macd_signal", "macd_hist"]

    def test_compute_moving_averages_returns_dataframe(self, simple_close: pd.Series) -> None:
        result = self.mod.compute_moving_averages(simple_close)
        assert isinstance(result, pd.DataFrame)
        pd.testing.assert_index_equal(result.index, simple_close.index)

    def test_compute_log_returns_returns_dataframe(self, simple_close: pd.Series) -> None:
        result = self.mod.compute_log_returns(simple_close)
        assert isinstance(result, pd.DataFrame)
        pd.testing.assert_index_equal(result.index, simple_close.index)

    def test_compute_volatility_rank_returns_series(self, volatile_close: pd.Series) -> None:
        result = self.mod.compute_volatility_rank(volatile_close)
        assert isinstance(result, pd.Series)
        pd.testing.assert_index_equal(result.index, volatile_close.index)

    def test_compute_all_features_ticker_forwarded(self) -> None:
        close = pd.Series(np.linspace(100, 200, 60))
        df = pd.DataFrame({"adjusted_close": close, "ticker": ["TEST"] * 60})
        result = self.mod.compute_all_features(df)
        assert "ticker" in result.columns
        assert (result["ticker"] == "TEST").all()
