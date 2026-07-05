"""
Evaluation metrics for the GlobalLSTM model.

All functions operate on numpy arrays (not tensors) for easy logging and plotting.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)


@torch.no_grad()
def evaluate(
    model: GlobalLSTM,
    dataloader: DataLoader,
    device: torch.device,
) -> dict[str, Any]:
    """Comprehensive evaluation on a DataLoader.

    Args:
        model: GlobalLSTM instance.
        dataloader: DataLoader (typically test set).
        device: torch.device.

    Returns:
        Dict with keys: accuracy, per_class_f1, confusion_matrix,
        directional_accuracy, simulated_sharpe.
    """
    model.eval()
    all_preds: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        ticker_idxs = ticker_idxs.to(device)

        logits = model(features, ticker_idxs)
        preds = logits.argmax(dim=-1)

        all_preds.append(preds.cpu().numpy())
        all_labels.append(labels.numpy())

    preds = np.concatenate(all_preds)
    labels = np.concatenate(all_labels)

    # Directional accuracy (overall)
    accuracy = float((preds == labels).mean())

    # Per-class metrics
    per_class_f1 = _compute_per_class_f1(labels, preds, n_classes=ML_CONFIG.N_CLASSES)
    confusion_matrix = _compute_confusion_matrix(labels, preds, n_classes=ML_CONFIG.N_CLASSES)

    # Directional accuracy (UP vs DOWN only, ignoring FLAT)
    directional_mask = labels != 1
    if directional_mask.sum() > 0:
        directional_acc = float((preds[directional_mask] == labels[directional_mask]).mean())
    else:
        directional_acc = 0.0

    # Simulated Sharpe (long-only)
    simulated_sharpe = compute_simulated_sharpe(labels, preds)

    # Long-short Sharpe (long UP, short DOWN)
    long_short_sharpe = compute_long_short_sharpe(labels, preds)

    return {
        "accuracy": accuracy,
        "directional_accuracy": directional_acc,
        "per_class_f1": per_class_f1,
        "confusion_matrix": confusion_matrix.tolist(),
        "simulated_sharpe": simulated_sharpe,
        "long_short_sharpe": long_short_sharpe,
        "total_samples": len(labels),
    }


def _compute_per_class_f1(
    labels: np.ndarray,
    preds: np.ndarray,
    n_classes: int = 3,
) -> dict[str, float]:
    """Compute per-class F1 score.

    Uses sklearn.metrics.f1_score with 'macro' average.

    Returns:
        Dict mapping class name to F1 score.
    """
    from sklearn.metrics import f1_score

    f1 = f1_score(labels, preds, average=None, labels=np.arange(n_classes), zero_division=0)
    return {f"{ML_CONFIG.CLASS_NAMES[i]}": float(f1[i]) for i in range(n_classes) if i < len(f1)}


def _compute_confusion_matrix(
    labels: np.ndarray,
    preds: np.ndarray,
    n_classes: int = 3,
) -> np.ndarray:
    """Compute confusion matrix.

    Returns:
        (n_classes, n_classes) numpy array.
    """
    from sklearn.metrics import confusion_matrix

    return confusion_matrix(labels, preds, labels=np.arange(n_classes))


def compute_simulated_sharpe(
    labels: np.ndarray,
    preds: np.ndarray,
    annual_factor: float = 252.0,
) -> float:
    """Compute Sharpe ratio from a simulated trading strategy.

    Strategy: Long the ticker when model predicts UP (class 2).
    Flat (cash) when model predicts FLAT (class 1) or DOWN (class 0).

    Daily return from strategy:
        - If prediction is UP: return = market_return (from labels)
        - If prediction is FLAT/DOWN: return = 0 (cash)

    Since we're simulating from historical labels, we use the actual
    market return when the strategy is long.

    Args:
        labels: True class labels (0=DOWN, 1=FLAT, 2=UP).
        preds: Predicted class labels.
        annual_factor: Number of trading days per year.

    Returns:
        Annualised Sharpe ratio. Returns 0.0 if std is 0.
    """
    # Strategy daily returns: long when prediction is UP, cash otherwise
    # For simulation, we need actual daily returns. Convert labels back:
    # UP (2) -> positive return, DOWN (0) -> negative return, FLAT (1) -> zero
    # Use approximate returns from label severity
    # ponytail: uses label as proxy for return magnitude. Replace with actual
    # log returns when available from the dataset for more accurate simulation.

    # Binary signal: 1.0 when long (pred=UP), 0.0 when flat (pred=FLAT/DOWN)
    signal = (preds == 2).astype(float)

    # Actual market returns: approximate from labels
    # DOWN -> -1%, FLAT -> 0%, UP -> +1% (normalised approximation)
    # ponytail: 1% per directional day is a rough proxy. Replace with actual
    # forward returns from the feature engineering pipeline for accuracy.
    market_returns = np.where(labels == 2, 0.01, np.where(labels == 0, -0.01, 0.0))

    # Strategy returns
    strategy_returns = signal * market_returns

    mean_return = float(np.mean(strategy_returns))
    std_return = float(np.std(strategy_returns))

    if std_return == 0.0:
        return 0.0

    # Annualise
    annualised_return = mean_return * annual_factor
    annualised_std = std_return * np.sqrt(annual_factor)
    sharpe = annualised_return / annualised_std

    return float(sharpe)


def compute_long_short_sharpe(
    labels: np.ndarray,
    preds: np.ndarray,
    annual_factor: float = 252.0,
) -> float:
    """Compute Sharpe ratio from a long-short trading strategy.

    Strategy: Long when model predicts UP (+1), short when model predicts
    DOWN (-1), flat (cash) when FLAT (0).

    This doubles the return signal compared to long-only: correct UP
    predictions earn +1%, correct DOWN predictions also earn +1%
    (shorting a -1% move). Incorrect predictions lose -1% in either
    direction. A symmetric model gets 2x the long-only Sharpe; an
    asymmetric model that's good at UP but bad at DOWN gets penalised.

    This is a more honest evaluation metric for directional forecasting
    since the model should profit from both UP and DOWN predictions.

    Args:
        labels: True class labels (0=DOWN, 1=FLAT, 2=UP).
        preds: Predicted class labels.
        annual_factor: Number of trading days per year.

    Returns:
        Annualised Sharpe ratio. Returns 0.0 if std is 0.
    """
    # Signal: +1 (long UP), -1 (short DOWN), 0 (flat)
    signal = np.where(preds == 2, 1.0, np.where(preds == 0, -1.0, 0.0))

    # Market returns: +1% for UP, -1% for DOWN, 0% for FLAT
    market_returns = np.where(labels == 2, 0.01, np.where(labels == 0, -0.01, 0.0))

    # Strategy returns: signal × market_return
    # Correct UP: (+1) × (+0.01) = +0.01
    # Correct DOWN: (-1) × (-0.01) = +0.01
    # Wrong UP: (+1) × (-0.01) = -0.01
    # Wrong DOWN: (-1) × (+0.01) = -0.01
    strategy_returns = signal * market_returns

    mean_return = float(np.mean(strategy_returns))
    std_return = float(np.std(strategy_returns))

    if std_return == 0.0:
        return 0.0

    annualised_return = mean_return * annual_factor
    annualised_std = std_return * np.sqrt(annual_factor)
    return float(annualised_return / annualised_std)


def plot_confusion_matrix(
    cm: np.ndarray,
    class_names: tuple[str, ...] = ML_CONFIG.CLASS_NAMES,
    save_path: str = "/tmp/confusion_matrix.png",
) -> str:
    """Plot and save confusion matrix.

    Args:
        cm: (n_classes, n_classes) confusion matrix.
        class_names: Class label names.
        save_path: File path to save the plot.

    Returns:
        Path to the saved plot.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
    ax.figure.colorbar(im, ax=ax)

    ax.set(
        xticks=np.arange(len(class_names)),
        yticks=np.arange(len(class_names)),
        xticklabels=class_names,
        yticklabels=class_names,
        xlabel="Predicted",
        ylabel="True",
    )

    # Rotate tick labels
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    # Display values
    for i in range(len(class_names)):
        for j in range(len(class_names)):
            ax.text(
                j,
                i,
                str(int(cm[i, j])),
                ha="center",
                va="center",
                color="white" if cm[i, j] > cm.max() / 2 else "black",
            )

    plt.tight_layout()
    plt.savefig(save_path, dpi=100, bbox_inches="tight")
    plt.close()
    return save_path


def plot_loss_curves(
    train_losses: list[float],
    val_losses: list[float],
    save_path: str = "/tmp/loss_curves.png",
) -> str:
    """Plot and save training and validation loss curves.

    Args:
        train_losses: List of training losses per epoch.
        val_losses: List of validation losses per epoch.
        save_path: File path to save the plot.

    Returns:
        Path to the saved plot.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    epochs = range(1, len(train_losses) + 1)
    ax.plot(epochs, train_losses, label="Training Loss", marker="o")
    ax.plot(epochs, val_losses, label="Validation Loss", marker="s")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Loss")
    ax.set_title("Training and Validation Loss")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=100, bbox_inches="tight")
    plt.close()
    return save_path
