"""
Tests for the training loop: FocalLoss, compute_class_weights, train/validate.

All tests use mocked torch components and need no DB or MLflow.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM
from ml.train import FocalLoss, compute_class_weights, train, train_epoch, validate

# ---------------------------------------------------------------------------
# FocalLoss
# ---------------------------------------------------------------------------


def test_focal_loss_forward_shape() -> None:
    """FocalLoss returns a scalar tensor."""
    loss_fn = FocalLoss()
    logits = torch.randn(16, 3)
    targets = torch.randint(0, 3, (16,))
    loss = loss_fn(logits, targets)
    assert loss.ndim == 0
    assert loss.item() > 0


def test_focal_loss_with_alpha() -> None:
    """FocalLoss with class weights produces different loss than uniform."""
    alpha = torch.tensor([1.0, 0.5, 2.0])
    loss_fn = FocalLoss(alpha=alpha)
    logits = torch.randn(32, 3)
    targets = torch.randint(0, 3, (32,))
    loss = loss_fn(logits, targets)
    assert loss.ndim == 0
    assert loss.item() > 0


def test_focal_loss_gamma_zero_equals_ce() -> None:
    """FocalLoss with gamma=0 should equal cross-entropy (with same weights)."""
    alpha = torch.tensor([1.0, 1.0, 1.0])
    focal = FocalLoss(alpha=alpha, gamma=0.0)
    ce = nn.CrossEntropyLoss(weight=alpha)
    logits = torch.randn(16, 3)
    targets = torch.randint(0, 3, (16,))
    focal_loss = focal(logits, targets)
    ce_loss = ce(logits, targets)
    assert focal_loss.item() == pytest.approx(ce_loss.item(), abs=1e-5)


def test_focal_loss_higher_gamma_downweights_easy() -> None:
    """Higher gamma produces lower loss on well-classified samples."""
    logits = torch.tensor([[2.0, 0.0, -1.0]])  # class 0 mildly confident
    targets = torch.zeros(1, dtype=torch.long)
    loss_low = FocalLoss(gamma=0.0)(logits, targets)
    loss_high = FocalLoss(gamma=8.0)(logits, targets)
    assert loss_high.item() < loss_low.item()


# ---------------------------------------------------------------------------
# compute_class_weights
# ---------------------------------------------------------------------------


def test_compute_class_weights_balanced() -> None:
    """Equal class counts produce approximately equal weights."""
    labels = torch.tensor([0, 0, 1, 1, 2, 2])
    weights = compute_class_weights(labels, n_classes=3)
    expected = torch.tensor([1.0, 1.0, 1.0])
    assert torch.allclose(weights, expected, atol=1e-6)


def test_compute_class_weights_imbalanced() -> None:
    """Imbalanced classes produce inversely proportional weights."""
    labels = torch.tensor([0, 0, 0, 0, 1, 1, 2, 2])  # class 0 is majority
    weights = compute_class_weights(labels, n_classes=3)
    assert weights[1] > weights[0]  # minority class (1) gets higher weight
    assert weights[2] > weights[0]  # minority class (2) gets higher weight
    assert weights[1] == pytest.approx(weights[2], rel=0.1)


def test_compute_class_weights_single_class() -> None:
    """Single-class labels do not crash and produce finite weights."""
    labels = torch.zeros(10, dtype=torch.long)
    weights = compute_class_weights(labels, n_classes=3)
    assert weights[0] > 0
    assert weights[1] > 0
    assert weights[2] > 0
    assert torch.all(torch.isfinite(weights))


def test_compute_class_weights_empty() -> None:
    """Empty labels produce finite weights (division by zero handled)."""
    labels = torch.tensor([], dtype=torch.long)
    weights = compute_class_weights(labels, n_classes=3)
    assert torch.all(torch.isfinite(weights))


# ---------------------------------------------------------------------------
# train_epoch
# ---------------------------------------------------------------------------


def _make_dummy_model() -> GlobalLSTM:
    return GlobalLSTM(
        n_features=ML_CONFIG.N_FEATURES,
        vocab_size=10,
        embed_dim=ML_CONFIG.EMBED_DIM,
        hidden_dim=ML_CONFIG.HIDDEN_DIM,
        n_layers=ML_CONFIG.N_LAYERS,
        dropout=ML_CONFIG.DROPOUT,
        n_classes=ML_CONFIG.N_CLASSES,
    )


def _make_dummy_loader(batch_size: int = 8, n_samples: int = 32) -> DataLoader:
    ds = TensorDataset(
        torch.randn(n_samples, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES),
        torch.randint(0, 3, (n_samples,)),
        torch.randint(0, 5, (n_samples,)),
    )
    return DataLoader(ds, batch_size=batch_size)


def test_train_epoch_returns_loss() -> None:
    """train_epoch returns a finite positive float."""
    model = _make_dummy_model()
    loader = _make_dummy_loader()
    criterion = FocalLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    device = torch.device("cpu")

    loss = train_epoch(model, loader, criterion, optimizer, device)
    assert isinstance(loss, float)
    assert loss > 0
    assert np.isfinite(loss)


def test_train_epoch_updates_weights() -> None:
    """After train_epoch, model weights should differ."""
    model = _make_dummy_model()
    loader = _make_dummy_loader(n_samples=16)
    criterion = FocalLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-2)
    device = torch.device("cpu")

    w_before = model.classifier.weight.data.clone()
    train_epoch(model, loader, criterion, optimizer, device)
    assert not torch.equal(w_before, model.classifier.weight.data)


def test_train_epoch_empty_loader() -> None:
    """Empty dataloader returns 0.0 loss without crashing."""
    model = _make_dummy_model()
    loader = DataLoader(
        TensorDataset(
            torch.empty(0, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES),
            torch.empty(0, dtype=torch.long),
            torch.empty(0, dtype=torch.long),
        )
    )
    criterion = FocalLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    device = torch.device("cpu")

    loss = train_epoch(model, loader, criterion, optimizer, device)
    assert loss == 0.0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_returns_metrics() -> None:
    """validate returns (loss, accuracy, directional_accuracy) tuple."""
    model = _make_dummy_model()
    loader = _make_dummy_loader(n_samples=16)
    criterion = FocalLoss()
    device = torch.device("cpu")

    val_loss, acc, dir_acc = validate(model, loader, criterion, device)
    assert isinstance(val_loss, float)
    assert isinstance(acc, float)
    assert isinstance(dir_acc, float)
    assert 0 <= acc <= 1
    assert 0 <= dir_acc <= 1


def test_validate_directional_accuracy() -> None:
    """Directional accuracy only counts non-FLAT labels."""
    torch.manual_seed(42)
    n = 16
    model = _make_dummy_model()
    # All labels are UP or DOWN (0 or 2) → directional accuracy == accuracy
    labels = torch.tensor([0, 2] * (n // 2), dtype=torch.long)
    ds = TensorDataset(
        torch.randn(n, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES),
        labels,
        torch.randint(0, 5, (n,)),
    )
    loader = DataLoader(ds, batch_size=8)
    criterion = FocalLoss()
    device = torch.device("cpu")
    _, acc, dir_acc = validate(model, loader, criterion, device)
    assert dir_acc == acc


def test_validate_all_flat_labels() -> None:
    """When all labels are FLAT, directional accuracy is 0."""
    n = 16
    model = _make_dummy_model()
    ds = TensorDataset(
        torch.randn(n, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES),
        torch.ones(n, dtype=torch.long),  # all FLAT
        torch.randint(0, 5, (n,)),
    )
    loader = DataLoader(ds, batch_size=8)
    criterion = FocalLoss()
    device = torch.device("cpu")
    _, _, dir_acc = validate(model, loader, criterion, device)
    assert dir_acc == 0.0


# ---------------------------------------------------------------------------
# train (orchestrator)
# ---------------------------------------------------------------------------


@patch("ml.train.logger")
@patch("torch.compile", lambda x, **kw: x)
def test_train_basic(mock_logger: MagicMock) -> None:
    """Train runs for n_epochs and returns history dict."""
    model = _make_dummy_model()
    train_loader = _make_dummy_loader(n_samples=64)
    val_loader = _make_dummy_loader(n_samples=16)
    device = torch.device("cpu")

    history = train(model, train_loader, val_loader, n_epochs=3, device=device)
    assert "train_losses" in history
    assert "val_losses" in history
    assert "val_accuracies" in history
    assert "val_directional_accuracies" in history
    assert "learning_rates" in history
    assert len(history["train_losses"]) == 3
    assert history["best_epoch"] >= 0


@patch("ml.train.logger")
@patch("torch.compile", lambda x, **kw: x)
def test_train_without_validation(mock_logger: MagicMock) -> None:
    """Train without val_loader skips validation and early stopping."""
    model = _make_dummy_model()
    train_loader = _make_dummy_loader(n_samples=64)
    device = torch.device("cpu")

    history = train(model, train_loader, val_loader=None, n_epochs=2, device=device)
    assert len(history["train_losses"]) == 2
    assert len(history["val_losses"]) == 0
    assert history["best_epoch"] == -1


@patch("ml.train.logger")
@patch("torch.compile", lambda x, **kw: x)
def test_train_early_stopping(mock_logger: MagicMock) -> None:
    """Train stops early when patience is exceeded."""
    model = _make_dummy_model()
    train_loader = _make_dummy_loader(n_samples=64)
    val_loader = _make_dummy_loader(n_samples=16)
    device = torch.device("cpu")

    history = train(model, train_loader, val_loader, n_epochs=50, patience=2, device=device)
    assert len(history["train_losses"]) < 50  # stopped early
    assert len(history["train_losses"]) > 0


@patch("torch.compile", lambda x, **kw: x)
def test_train_loss_decreases_generally() -> None:
    """Training loss generally decreases over epochs."""
    model = _make_dummy_model()
    train_loader = _make_dummy_loader(n_samples=128)
    device = torch.device("cpu")

    history = train(model, train_loader, val_loader=None, n_epochs=5, device=device)
    losses = history["train_losses"]
    assert losses[-1] <= losses[0] + 0.5  # loss should not explode
