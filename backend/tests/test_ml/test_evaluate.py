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
        assert "coverage" in metrics
        assert "margin" in metrics
        assert "total_samples" in metrics
        assert metrics["total_samples"] == 20
        # No forward-return data supplied → Sharpe metrics stay None.
        assert metrics["sharpe_long_only_0bps"] is None
        assert metrics["sharpe_long_short_0bps"] is None


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


class TestMarginRule:
    """|p_up − p_down| < margin ⇒ FLAT (abstain)."""

    def test_edge_ge_margin_up(self) -> None:
        from ml.evaluate import apply_margin_rule

        probs = np.array([[0.2, 0.1, 0.7], [0.45, 0.1, 0.45]])
        preds = apply_margin_rule(probs, margin=0.2)
        assert preds[0] == 2  # edge 0.5 ≥ 0.2 → UP
        assert preds[1] == 1  # edge 0.0 < 0.2 → FLAT (abstain)

    def test_negative_edge_down(self) -> None:
        from ml.evaluate import apply_margin_rule

        probs = np.array([[0.7, 0.1, 0.2]])
        assert apply_margin_rule(probs, margin=0.3)[0] == 0

    def test_zero_margin_collapses_to_binary(self) -> None:
        from ml.evaluate import apply_margin_rule

        probs = np.array([[0.34, 0.33, 0.33], [0.2, 0.5, 0.3]])
        preds = apply_margin_rule(probs, margin=0.0)
        # edge = p_up − p_down; ≥ 0 → UP, < 0 → DOWN (FLAT never predicted)
        assert list(preds) == [0, 2]


class TestEvaluateFromProbs:
    def test_margin_and_coverage(self) -> None:
        from ml.evaluate import evaluate_from_probs

        labels = np.array([2, 0, 1, 2, 0])
        probs = np.array(
            [
                [0.1, 0.1, 0.8],  # edge 0.7 → UP, label UP → correct
                [0.8, 0.1, 0.1],  # edge −0.7 → DOWN, label DOWN → correct
                [0.4, 0.2, 0.4],  # edge 0.0 → FLAT (abstain, label FLAT)
                [0.1, 0.1, 0.8],  # UP, label UP → correct
                [0.1, 0.1, 0.8],  # UP, label DOWN → wrong
            ]
        )
        m = evaluate_from_probs(probs, labels, margin=0.2)
        assert m["total_samples"] == 5
        assert m["coverage"] == pytest.approx(4 / 5)
        assert m["margin"] == pytest.approx(0.2)
        assert m["n_directional"] == 4
        assert m["n_directional_correct"] == 3
        assert m["directional_accuracy"] == pytest.approx(0.75)

    def test_sharpe_with_forward_returns(self) -> None:
        from ml.evaluate import evaluate_from_probs

        n = 30
        labels = np.full(n, 2)
        probs = np.tile([0.2, 0.1, 0.7], (n, 1))  # always UP
        fwd_rets = np.linspace(0.001, 0.01, n)
        dates = np.array(
            np.datetime64("2024-01-01") + np.arange(n) * np.timedelta64(1, "D"),
            dtype="datetime64[D]",
        )
        m = evaluate_from_probs(
            probs,
            labels,
            fwd_rets=fwd_rets,
            dates=dates,
            ticker_idxs=np.zeros(n, dtype=np.int64),
        )
        assert m["sharpe_long_only_0bps"] is not None
        assert m["sharpe_long_only_0bps"] > 0
        assert m["sharpe_long_only_10bps"] is not None
        assert m["sharpe_long_only_10bps"] < m["sharpe_long_only_0bps"]


class TestRealSharpe:
    """Real forward-return Sharpe (replaces the old ±1% label proxy)."""

    @staticmethod
    def _synth(n: int = 30, seed: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        fwd_rets = rng.normal(0.001, 0.004, size=n)
        dates = np.array(
            np.datetime64("2024-01-01") + np.arange(n) * np.timedelta64(1, "D"),
            dtype="datetime64[D]",
        )
        return fwd_rets, dates, np.zeros(n, dtype=np.int64)

    def test_perfect_up_prediction_positive_long_sharpe(self) -> None:
        from ml.evaluate import _strategy_sharpe

        fwd_rets, dates, ticker_idxs = self._synth()
        labels = np.where(fwd_rets > 0, 2, 0)
        sharpe = _strategy_sharpe(
            labels, fwd_rets, dates, ticker_idxs, mode="long_only", cost_bps=0
        )
        assert sharpe > 0

    def test_always_flat_gives_zero(self) -> None:
        from ml.evaluate import _strategy_sharpe

        fwd_rets, dates, ticker_idxs = self._synth()
        preds = np.ones(len(fwd_rets), dtype=np.int64)
        sharpe = _strategy_sharpe(
            preds, fwd_rets, dates, ticker_idxs, mode="long_short", cost_bps=0
        )
        assert sharpe == 0.0

    def test_wrong_direction_negative(self) -> None:
        from ml.evaluate import _strategy_sharpe

        fwd_rets, dates, ticker_idxs = self._synth()
        labels = np.where(fwd_rets > 0, 2, 0)
        preds = np.where(labels == 2, 0, 2)  # always wrong direction
        sharpe = _strategy_sharpe(
            preds, fwd_rets, dates, ticker_idxs, mode="long_short", cost_bps=0
        )
        assert sharpe < 0


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


class TestDirectionalCounts:
    """evaluate() must expose the challenger counts the promotion gate needs."""

    @staticmethod
    def _run_evaluate(labels: np.ndarray) -> dict:
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
        n = len(labels)
        sequences = np.random.randn(n, 30, ML_CONFIG.N_FEATURES).astype(np.float32)
        ds = SequenceDataset(sequences, labels, np.zeros(n, dtype=np.int64))
        return evaluate(model, DataLoader(ds, batch_size=8), torch.device("cpu"))

    def test_counts_consistent_with_accuracy(self) -> None:
        rng = np.random.default_rng(7)
        metrics = self._run_evaluate(rng.integers(0, 3, size=20))

        n = metrics["n_directional"]
        k = metrics["n_directional_correct"]
        assert isinstance(n, int) and isinstance(k, int)
        assert 0 <= k <= n <= metrics["total_samples"]
        if n > 0:
            assert metrics["directional_accuracy"] == pytest.approx(k / n)

    def test_all_flat_gives_zero_directional(self) -> None:
        metrics = self._run_evaluate(np.ones(20, dtype=np.int64))  # FLAT == 1

        assert metrics["n_directional"] == 0
        assert metrics["n_directional_correct"] == 0
        assert metrics["directional_accuracy"] == 0.0
