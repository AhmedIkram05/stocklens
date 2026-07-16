"""
Tests for DriftDetector service class (src.drift.service).

Tests PSI, KS, JS computations and the compute_drift orchestration.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.drift.service import (
    FEATURE_NAMES,
    DriftDetector,
    compute_js_divergence,
    compute_ks_statistic,
    compute_prediction_distribution,
    compute_psi,
)


class TestComputePSI:
    """Tests for compute_psi (Population Stability Index)."""

    def test_identical_arrays_zero_psi(self):
        ref = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cur = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert compute_psi(ref, cur) == 0.0

    def test_different_distributions_positive_psi(self):
        ref = np.array([1.0] * 100 + [2.0] * 100)
        cur = np.array([1.0] * 50 + [2.0] * 150)
        psi = compute_psi(ref, cur)
        assert psi > 0

    def test_single_element_returns_zero(self):
        assert compute_psi(np.array([1.0]), np.array([1.0])) == 0.0

    def test_empty_arrays_return_zero(self):
        assert compute_psi(np.array([]), np.array([])) == 0.0

    def test_nan_handled(self):
        ref = np.array([1.0, np.nan, 3.0])
        cur = np.array([1.0, 2.0, 3.0])
        psi = compute_psi(ref, cur)
        assert psi >= 0

    def test_all_same_value_returns_zero(self):
        ref = np.array([5.0, 5.0, 5.0])
        cur = np.array([5.0, 5.0, 5.0])
        assert compute_psi(ref, cur) == 0.0


class TestComputeKSStatistic:
    """Tests for compute_ks_statistic (Kolmogorov-Smirnov test)."""

    def test_identical_distributions(self):
        ref = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cur = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_ks_statistic(ref, cur)
        assert result["statistic"] == 0.0
        assert result["p_value"] == 1.0

    def test_different_distributions(self):
        ref = np.random.normal(0, 1, 1000)
        cur = np.random.normal(1, 1, 1000)
        result = compute_ks_statistic(ref, cur)
        assert result["statistic"] > 0
        assert 0 <= result["p_value"] <= 1

    def test_empty_arrays(self):
        result = compute_ks_statistic(np.array([]), np.array([]))
        assert result["statistic"] == 0.0
        assert result["p_value"] == 1.0

    def test_single_element_arrays(self):
        result = compute_ks_statistic(np.array([1.0]), np.array([2.0]))
        assert result["statistic"] == 0.0
        assert result["p_value"] == 1.0

    def test_nan_filtered(self):
        ref = np.array([1.0, np.nan, 3.0])
        cur = np.array([1.0, 2.0, np.nan])
        result = compute_ks_statistic(ref, cur)
        assert "statistic" in result
        assert "p_value" in result


class TestComputeJSDivergence:
    """Tests for compute_js_divergence (Jensen-Shannon divergence)."""

    def test_identical_distributions_zero(self):
        p = np.array([0.2, 0.3, 0.5])
        q = np.array([0.2, 0.3, 0.5])
        assert compute_js_divergence(p, q) == 0.0

    def test_different_distributions_positive(self):
        p = np.array([1.0, 0.0, 0.0])
        q = np.array([0.0, 1.0, 0.0])
        js = compute_js_divergence(p, q)
        assert 0 < js <= 1.0

    def test_empty_arrays(self):
        assert compute_js_divergence(np.array([]), np.array([])) == 0.0

    def test_unnormalized_inputs_normalized(self):
        p = np.array([10, 20, 30])
        q = np.array([5, 15, 25])
        js = compute_js_divergence(p, q)
        assert 0 <= js <= 1.0

    def test_zeros_handled(self):
        p = np.array([0.5, 0.5, 0.0])
        q = np.array([0.0, 0.5, 0.5])
        js = compute_js_divergence(p, q)
        assert 0 <= js <= 1.0


class TestComputePredictionDistribution:
    """Tests for compute_prediction_distribution."""

    def test_basic_distribution(self):
        predictions = ["UP", "DOWN", "FLAT", "UP", "UP"]
        dist = compute_prediction_distribution(predictions)
        assert dist.shape == (3,)
        assert abs(dist.sum() - 1.0) < 1e-10
        assert dist[0] == 3 / 5  # UP
        assert dist[1] == 1 / 5  # DOWN
        assert dist[2] == 1 / 5  # FLAT

    def test_unknown_predictions_ignored(self):
        predictions = ["UP", "UNKNOWN", "DOWN", "INVALID", "FLAT"]
        dist = compute_prediction_distribution(predictions)
        assert dist[0] == 1 / 3  # UP
        assert dist[1] == 1 / 3  # DOWN
        assert dist[2] == 1 / 3  # FLAT

    def test_empty_predictions(self):
        dist = compute_prediction_distribution([])
        assert np.array_equal(dist, np.array([1 / 3, 1 / 3, 1 / 3]))

    def test_custom_classes(self):
        predictions = ["A", "B", "A", "C"]
        dist = compute_prediction_distribution(predictions, classes=("A", "B", "C"))
        assert dist[0] == 0.5
        assert dist[1] == 0.25
        assert dist[2] == 0.25


class TestDriftDetector:
    """Tests for DriftDetector.compute_drift."""

    def setup_method(self):
        self.detector = DriftDetector(psi_threshold=0.1, ks_threshold=0.1, js_threshold=0.1)

    @pytest.mark.asyncio
    async def test_empty_tickers_returns_empty_metrics(self):
        result = await self.detector.compute_drift(
            tickers=[],
            reference_dist={},
            prediction_logs={},
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )
        assert result["metrics"] == []
        assert result["alerts_triggered"] == 0
        assert result["overall_verdict"] == "stable"

    @pytest.mark.asyncio
    async def test_no_reference_data_no_feature_drift(self):
        result = await self.detector.compute_drift(
            tickers=["AAPL"],
            reference_dist={},
            prediction_logs={"AAPL": []},
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )
        # No feature-level drift without reference, but prediction JS still computed
        assert result["max_psi"] == 0.0
        assert result["max_js_divergence"] >= 0.0

    @pytest.mark.asyncio
    async def test_feature_level_drift_with_reference(self):
        ref_array = np.random.normal(0, 1, 1000)
        ref_histograms = {
            "log_ret_1d": {"values": ref_array.tolist()},
        }
        reference_dist = {"feature_histograms": ref_histograms}

        # Current data with shifted mean
        prediction_logs = {
            "AAPL": [{"features": {"stats": {"means": [0.5] + [0.0] * (len(FEATURE_NAMES) - 1)}}}]
            * 100
        }

        result = await self.detector.compute_drift(
            tickers=["AAPL"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        feature_metrics = [m for m in result["metrics"] if m["feature_name"] == "log_ret_1d"]
        assert len(feature_metrics) == 3  # PSI, KS, JS
        assert any(m["metric_type"] == "psi" for m in feature_metrics)

    @pytest.mark.asyncio
    async def test_prediction_distribution_drift(self):
        ref_props = {"UP": 0.33, "DOWN": 0.33, "FLAT": 0.34}
        reference_dist = {"prediction_proportions": ref_props}

        # Skewed predictions
        prediction_logs = {
            "AAPL": [{"prediction": "UP"}] * 80
            + [{"prediction": "DOWN"}] * 10
            + [{"prediction": "FLAT"}] * 10
        }

        result = await self.detector.compute_drift(
            tickers=["AAPL"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        pred_js_metrics = [m for m in result["metrics"] if m["metric_type"] == "prediction_js"]
        assert len(pred_js_metrics) == 1
        assert pred_js_metrics[0]["feature_name"] == "prediction_distribution"

    @pytest.mark.asyncio
    async def test_alert_triggered_when_threshold_exceeded(self):
        detector = DriftDetector(psi_threshold=0.01, ks_threshold=0.01, js_threshold=0.01)
        ref_array = np.random.normal(0, 1, 1000)
        reference_dist = {"feature_histograms": {"log_ret_1d": {"values": ref_array.tolist()}}}

        prediction_logs = {
            "AAPL": [{"features": {"stats": {"means": [2.0] + [0.0] * (len(FEATURE_NAMES) - 1)}}}]
            * 100
        }

        result = await detector.compute_drift(
            tickers=["AAPL"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        psi_alert = next(m for m in result["metrics"] if m["metric_type"] == "psi")
        assert psi_alert["alert_triggered"] is True
        assert result["alerts_triggered"] > 0
        assert result["overall_verdict"] == "drifted"

    @pytest.mark.asyncio
    async def test_multiple_tickers_processed(self):
        from src.drift.service import DriftDetector

        ref_array = np.random.normal(0, 1, 1000)
        reference_dist = {"feature_histograms": {"log_ret_1d": {"values": ref_array.tolist()}}}
        prediction_logs = {
            "AAPL": [{"features": {"stats": {"means": [0.1] + [0.0] * (len(FEATURE_NAMES) - 1)}}}]
            * 50,
            "MSFT": [{"features": {"stats": {"means": [0.05] + [0.0] * (len(FEATURE_NAMES) - 1)}}}]
            * 50,
        }

        detector = DriftDetector()
        result = await detector.compute_drift(
            tickers=["AAPL", "MSFT"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        assert result["metrics"]
        tickers_in_metrics = {m["ticker"] for m in result["metrics"]}
        assert tickers_in_metrics == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_single_prediction_log(self):
        from src.drift.service import DriftDetector

        reference_dist = {"feature_histograms": {"log_ret_1d": {"values": [0.0] * 10}}}
        prediction_logs = {
            "AAPL": [{"features": {"stats": {"means": [0.1] + [0.0] * (len(FEATURE_NAMES) - 1)}}}]
        }

        detector = DriftDetector()
        result = await detector.compute_drift(
            tickers=["AAPL"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        assert result["metrics"]

    @pytest.mark.asyncio
    async def test_missing_features_handled_gracefully(self):
        from src.drift.service import DriftDetector

        reference_dist = {
            "feature_histograms": {"log_ret_1d": {"values": [0.0] * 10}},
            "prediction_proportions": {"UP": 0.33, "DOWN": 0.33, "FLAT": 0.34},
        }
        # Log entry missing features
        prediction_logs = {"AAPL": [{"prediction": "UP"}]}

        detector = DriftDetector()
        result = await detector.compute_drift(
            tickers=["AAPL"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        # Should not crash, prediction JS computed
        pred_js = [m for m in result["metrics"] if m["metric_type"] == "prediction_js"]
        assert len(pred_js) == 1

    @pytest.mark.asyncio
    async def test_duplicate_predictions_aggregated(self):
        from src.drift.service import DriftDetector

        reference_dist = {"feature_histograms": {"log_ret_1d": {"values": [0.0] * 10}}}
        prediction_logs = {
            "AAPL": [
                {"features": {"stats": {"means": [0.1] + [0.0] * (len(FEATURE_NAMES) - 1)}}},
                {"features": {"stats": {"means": [0.2] + [0.0] * (len(FEATURE_NAMES) - 1)}}},
            ]
        }

        detector = DriftDetector()
        result = await detector.compute_drift(
            tickers=["AAPL"],
            reference_dist=reference_dist,
            prediction_logs=prediction_logs,
            model_version="v1",
            drift_run_id="run-1",
            current_period="2024-01-01_2024-01-07",
        )

        assert len(result["metrics"]) >= 3  # PSI, KS, JS for the feature


class TestFeatureNames:
    """Test FEATURE_NAMES constant."""

    def test_has_expected_count(self):
        assert len(FEATURE_NAMES) == 17

    def test_expected_features_present(self):
        expected = [
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
        for e in expected:
            assert e in FEATURE_NAMES
