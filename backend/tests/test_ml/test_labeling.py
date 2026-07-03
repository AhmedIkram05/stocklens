"""Tests for ml/labeling.py - adaptive UP/FLAT/DOWN labeling."""

from __future__ import annotations

import numpy as np
import pandas as pd


class TestAdaptiveLabels:
    def test_up_trend(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series(np.linspace(100, 150, 100))
        labels = compute_adaptive_labels(close)
        assert (labels.dropna() == 2).sum() > (labels.dropna() == 0).sum()

    def test_down_trend(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series(np.linspace(150, 100, 100))
        labels = compute_adaptive_labels(close)
        assert (labels.dropna() == 0).sum() > (labels.dropna() == 2).sum()

    def test_flat_market(self) -> None:
        from ml.labeling import compute_adaptive_labels

        np.random.seed(42)
        close = pd.Series(100 + np.random.normal(0, 0.5, 200))
        labels = compute_adaptive_labels(close, threshold_mult=2.0)
        flat_ratio = (labels.dropna() == 1).sum() / labels.dropna().shape[0]
        assert flat_ratio > 0.5

    def test_threshold_zero(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series([100.0] * 50)
        labels = compute_adaptive_labels(close, threshold_mult=0.0)
        assert (labels.dropna() == 1).sum() == 0

    def test_all_nan_returns_nan(self) -> None:
        from ml.labeling import compute_adaptive_labels

        close = pd.Series([100.0])
        labels = compute_adaptive_labels(close)
        assert labels.isna().all()

    def test_random_walk_distribution(self) -> None:
        from ml.labeling import compute_adaptive_labels, compute_label_distribution

        np.random.seed(42)
        returns = np.random.normal(0, 0.01, 1000)
        close = pd.Series(100 * np.exp(np.cumsum(returns)))
        labels = compute_adaptive_labels(close)
        dist = compute_label_distribution(labels)
        assert 0.2 < dist["FLAT"] < 0.6
        assert 0.2 < dist["UP"] < 0.6
        assert 0.2 < dist["DOWN"] < 0.6

    def test_highly_volatile_has_fewer_flat(self) -> None:
        from ml.labeling import compute_adaptive_labels, compute_label_distribution

        np.random.seed(42)
        returns = np.random.normal(0, 0.05, 1000)
        close = pd.Series(100 * np.exp(np.cumsum(returns)))
        labels = compute_adaptive_labels(close, threshold_mult=0.5)
        dist = compute_label_distribution(labels)
        assert dist["FLAT"] < 0.4
