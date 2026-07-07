"""Tests for drift detection service — PSI, KS, JS, prediction distributions."""

from __future__ import annotations

import numpy as np

from src.drift.service import (
    compute_js_divergence,
    compute_ks_statistic,
    compute_prediction_distribution,
    compute_psi,
)


class TestComputePsi:
    """Population Stability Index tests."""

    def test_identical_distributions(self) -> None:
        ref = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cur = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        psi = compute_psi(ref, cur)
        assert psi < 0.01

    def test_very_different_distributions(self) -> None:
        ref = np.array([1.0, 1.0, 2.0, 2.0, 3.0])
        cur = np.array([100.0, 100.0, 110.0, 110.0, 120.0])
        psi = compute_psi(ref, cur)
        assert psi > 0.1

    def test_empty_arrays(self) -> None:
        assert compute_psi(np.array([]), np.array([1.0, 2.0])) == 0.0
        assert compute_psi(np.array([1.0, 2.0]), np.array([])) == 0.0

    def test_single_value(self) -> None:
        assert compute_psi(np.array([1.0]), np.array([2.0])) == 0.0

    def test_nan_handling(self) -> None:
        ref = np.array([1.0, np.nan, 3.0, 4.0, 5.0])
        cur = np.array([1.5, 2.5, np.nan, 4.5, 5.5])
        psi = compute_psi(ref, cur)
        assert not np.isnan(psi)
        assert psi >= 0.0

    def test_all_identical_values(self) -> None:
        ref = np.array([5.0, 5.0, 5.0])
        cur = np.array([5.0, 5.0, 5.0])
        psi = compute_psi(ref, cur)
        assert psi == 0.0

    def test_psi_drift_detected(self) -> None:
        ref = np.array([1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 1.5, 2.5, 3.5, 1.2])
        cur = np.array([5.0, 5.0, 6.0, 6.0, 7.0, 7.0, 5.5, 6.5, 7.5, 5.2])
        psi_ab = compute_psi(ref, cur)
        psi_ba = compute_psi(cur, ref)
        assert psi_ab > 0.1
        assert psi_ba > 0.1


class TestComputeKs:
    """Kolmogorov-Smirnov test tests."""

    def test_identical_distributions(self) -> None:
        ref = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cur = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        res = compute_ks_statistic(ref, cur)
        assert res["p_value"] > 0.05

    def test_different_distributions(self) -> None:
        ref = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        cur = np.array([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
        res = compute_ks_statistic(ref, cur)
        assert res["p_value"] < 0.01

    def test_empty_arrays(self) -> None:
        res = compute_ks_statistic(np.array([]), np.array([1.0, 2.0]))
        assert res["statistic"] == 0.0
        assert res["p_value"] == 1.0

    def test_nan_handling(self) -> None:
        ref = np.array([1.0, np.nan, 3.0])
        cur = np.array([1.5, np.nan, 3.5])
        res = compute_ks_statistic(ref, cur)
        assert not np.isnan(res["statistic"])
        assert not np.isnan(res["p_value"])

    def test_has_statistic_and_p_value_keys(self) -> None:
        res = compute_ks_statistic(
            np.array([1.0, 2.0, 3.0]),
            np.array([1.5, 2.5, 3.5]),
        )
        assert "statistic" in res
        assert "p_value" in res


class TestComputeJsDivergence:
    """Jensen-Shannon divergence tests."""

    def test_identical_distributions(self) -> None:
        p = np.array([0.5, 0.5])
        q = np.array([0.5, 0.5])
        js = compute_js_divergence(p, q)
        assert js < 0.01

    def test_different_distributions(self) -> None:
        p = np.array([0.9, 0.1])
        q = np.array([0.1, 0.9])
        js = compute_js_divergence(p, q)
        assert js > 0.1

    def test_bounded_0_to_1(self) -> None:
        for _ in range(10):
            p = np.random.dirichlet(np.ones(5))
            q = np.random.dirichlet(np.ones(5))
            js = compute_js_divergence(p, q)
            assert 0.0 <= js <= 1.0

    def test_identical_zero_entries(self) -> None:
        p = np.array([1.0, 0.0, 0.0])
        q = np.array([1.0, 0.0, 0.0])
        js = compute_js_divergence(p, q)
        assert js < 0.01

    def test_symmetric(self) -> None:
        p = np.array([0.7, 0.2, 0.1])
        q = np.array([0.1, 0.3, 0.6])
        js_pq = compute_js_divergence(p, q)
        js_qp = compute_js_divergence(q, p)
        assert abs(js_pq - js_qp) < 1e-10


class TestComputePredictionDistribution:
    """Prediction distribution histogram tests."""

    def test_even_distribution(self) -> None:
        preds = ["UP", "DOWN", "FLAT"]
        dist = compute_prediction_distribution(preds)
        assert np.allclose(dist, [1 / 3, 1 / 3, 1 / 3])

    def test_all_up(self) -> None:
        preds = ["UP", "UP", "UP"]
        dist = compute_prediction_distribution(preds)
        assert np.allclose(dist, [1.0, 0.0, 0.0])

    def test_empty_list(self) -> None:
        dist = compute_prediction_distribution([])
        assert np.allclose(dist, [0.0, 0.0, 0.0])

    def test_invalid_prediction_ignored(self) -> None:
        preds = ["UP", "INVALID", "DOWN"]
        dist = compute_prediction_distribution(preds)
        assert np.allclose(dist, [0.5, 0.5, 0.0])


class TestFeatureNames:
    """FEATURE_NAMES tuple consistency check."""

    def test_feature_names_count(self) -> None:
        from src.drift.service import FEATURE_NAMES

        assert len(FEATURE_NAMES) == 17

    def test_feature_names_content(self) -> None:
        from src.drift.service import FEATURE_NAMES

        assert "log_ret_1d" in FEATURE_NAMES
        assert "rsi_14" in FEATURE_NAMES
        assert "vol_30d" in FEATURE_NAMES
