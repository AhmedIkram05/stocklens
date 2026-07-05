"""Tests for ml/evaluate.py - evaluation metrics."""

from __future__ import annotations

import numpy as np
import pytest


class TestDirectionalAccuracy:
    def test_perfect_prediction(self) -> None:
        from ml.evaluate import _compute_confusion_matrix

        labels = np.array([0, 1, 2, 0, 1, 2])
        preds = np.array([0, 1, 2, 0, 1, 2])
        cm = _compute_confusion_matrix(labels, preds)
        assert np.trace(cm) == 6  # All diagonal

    def test_all_wrong(self) -> None:
        from ml.evaluate import _compute_confusion_matrix

        labels = np.array([0, 1, 2])
        preds = np.array([1, 2, 0])
        cm = _compute_confusion_matrix(labels, preds)
        assert np.trace(cm) == 0  # Nothing on diagonal

    def test_accuracy_calculation(self) -> None:
        from ml.evaluate import _compute_per_class_f1

        labels = np.array([0, 0, 1, 1, 2, 2])
        preds = np.array([0, 0, 1, 1, 2, 2])
        f1 = _compute_per_class_f1(labels, preds)
        assert f1["DOWN"] == pytest.approx(1.0)
        assert f1["FLAT"] == pytest.approx(1.0)
        assert f1["UP"] == pytest.approx(1.0)

    def test_evaluate_function(self) -> None:
        """Integration test: evaluate with a tiny model setup."""
        import torch
        from torch.utils.data import DataLoader

        from ml.config import ML_CONFIG
        from ml.dataset import SequenceDataset
        from ml.evaluate import evaluate
        from ml.model import GlobalLSTM

        model = GlobalLSTM(
            n_features=ML_CONFIG.N_FEATURES,
            vocab_size=5,
            embed_dim=4,
            hidden_dim=16,
            n_layers=1,
            dropout=0.0,
        )
        device = torch.device("cpu")

        # Create a tiny dataset
        sequences = np.random.randn(20, 30, ML_CONFIG.N_FEATURES).astype(np.float32)
        labels = np.random.randint(0, 3, size=20)
        ticker_idxs = np.zeros(20, dtype=np.int64)
        ds = SequenceDataset(sequences, labels, ticker_idxs)
        loader = DataLoader(ds, batch_size=8)

        metrics = evaluate(model, loader, device)
        assert "accuracy" in metrics
        assert "per_class_f1" in metrics
        assert "confusion_matrix" in metrics
        assert "simulated_sharpe" in metrics
        assert "long_short_sharpe" in metrics
        assert "total_samples" in metrics
        assert metrics["total_samples"] == 20


class TestPerClassF1:
    def test_imbalanced(self) -> None:
        from ml.evaluate import _compute_per_class_f1

        # Mostly DOWN (class 0), few UP (class 2)
        labels = np.array([0, 0, 0, 0, 0, 2, 2])
        preds = np.array([0, 0, 0, 0, 0, 0, 2])  # Missed one UP
        f1 = _compute_per_class_f1(labels, preds)
        assert f1["DOWN"] > 0.9
        assert f1["UP"] < 1.0  # Not perfect

    def test_single_class(self) -> None:
        from ml.evaluate import _compute_per_class_f1

        labels = np.array([1, 1, 1])
        preds = np.array([1, 1, 1])
        f1 = _compute_per_class_f1(labels, preds)
        assert f1["FLAT"] == pytest.approx(1.0)


class TestSimulatedSharpe:
    def test_perfect_up_strategy(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        # Mix of UP and FLAT so std > 0
        labels = np.array([2, 2, 1, 2, 2])  # True UP, UP, FLAT, UP, UP
        preds = np.array([2, 2, 1, 2, 2])  # Perfect predictions

        sharpe = compute_simulated_sharpe(labels, preds)
        assert sharpe > 0

    def test_always_wrong_strategy(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        # Always predict DOWN when UP is true -> always flat (no signal)
        labels = np.array([2, 2, 2])
        preds = np.array([0, 0, 0])

        sharpe = compute_simulated_sharpe(labels, preds)
        assert sharpe == 0.0  # No long positions

    def test_mixed_strategy(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        labels = np.array([2, 0, 2, 0])  # UP, DOWN, UP, DOWN
        preds = np.array([2, 2, 2, 2])  # Always predict UP

        sharpe = compute_simulated_sharpe(labels, preds)
        # Long on UP and DOWN days -> mixed returns
        assert isinstance(sharpe, float)

    def test_zero_std_returns_zero(self) -> None:
        from ml.evaluate import compute_simulated_sharpe

        # Single sample: std will be 0
        labels = np.array([2])
        preds = np.array([2])

        sharpe = compute_simulated_sharpe(labels, preds)
        assert sharpe == 0.0


class TestLongShortSharpe:
    def test_long_short_boosts_sharpe(self) -> None:
        """Long-short doubles signal vs long-only when model is right in both directions."""
        from ml.evaluate import compute_long_short_sharpe, compute_simulated_sharpe

        # Equal UP and DOWN, mostly correct, some wrong — gives variance for non-zero Sharpe
        labels = np.array([2, 2, 2, 0, 0, 0, 1, 1, 2, 0])
        preds = np.array([2, 2, 2, 0, 0, 0, 1, 1, 1, 1])  # last two wrong (pred FLAT)

        long_only = compute_simulated_sharpe(labels, preds)
        long_short = compute_long_short_sharpe(labels, preds)
        # Long-short captures signal from BOTH UP and DOWN, so mean return > long-only
        assert long_short > long_only
        assert long_short > 0

    def test_always_flat(self) -> None:
        """No signal = zero Sharpe."""
        from ml.evaluate import compute_long_short_sharpe

        labels = np.array([2, 0, 2, 0])
        preds = np.array([1, 1, 1, 1])  # Always FLAT

        sharpe = compute_long_short_sharpe(labels, preds)
        assert sharpe == 0.0

    def test_asymmetric_model_penalized(self) -> None:
        """Model that always predicts UP gets BOTH correct UP and wrong DOWN."""
        from ml.evaluate import compute_long_short_sharpe

        labels = np.array([2, 0, 2, 0])
        preds = np.array([2, 2, 2, 2])  # Always UP

        sharpe = compute_long_short_sharpe(labels, preds)
        # UP predictions earn +1%, DOWN predictions lose -1%
        # avg return = (0.01 + -0.01 + 0.01 + -0.01) / 4 = 0
        assert sharpe == 0.0

    def test_zero_std_returns_zero(self) -> None:
        from ml.evaluate import compute_long_short_sharpe

        labels = np.array([2])
        preds = np.array([2])

        sharpe = compute_long_short_sharpe(labels, preds)
        assert sharpe == 0.0


class TestPlotFunctions:
    def test_confusion_matrix_plot(self) -> None:
        from ml.evaluate import plot_confusion_matrix

        cm = np.array([[10, 2, 1], [3, 15, 2], [1, 2, 20]])
        path = plot_confusion_matrix(cm)
        assert path.endswith(".png")

    def test_loss_curves_plot(self) -> None:
        from ml.evaluate import plot_loss_curves

        path = plot_loss_curves(
            [0.8, 0.6, 0.4, 0.3],
            [0.9, 0.7, 0.5, 0.4],
        )
        assert path.endswith(".png")
