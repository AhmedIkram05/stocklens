"""
Evaluation metrics for the GlobalLSTM model.

All metrics operate on numpy arrays. Sharpe ratios are computed from the
ACTUAL forward log returns carried by each window (no label-magnitude
proxies). The decision rule supports abstention: when the margin between
P(UP) and P(DOWN) is below `margin`, the model predicts FLAT (no trade).
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

DOWN, FLAT, UP = 0, 1, 2


@torch.no_grad()
def predict_probs(
    model: GlobalLSTM,
    dataloader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    """Run inference and return class probabilities + labels.

    The dataloader must NOT shuffle so results align with any per-window
    metadata (forward returns, dates) taken from the source SequenceDataset.
    """
    model.eval()
    all_probs: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []

    for features, labels, _ticker_idxs in dataloader:
        features = features.to(device)
        ticker_idxs = _ticker_idxs.to(device)

        logits = model(features, ticker_idxs)
        all_probs.append(torch.softmax(logits, dim=-1).cpu().numpy())
        all_labels.append(labels.numpy())

    return np.concatenate(all_probs), np.concatenate(all_labels)


def apply_margin_rule(probs: np.ndarray, margin: float) -> np.ndarray:
    """Decision rule with abstention.

    Predict UP/DOWN only when |P(UP) - P(DOWN)| >= margin, else FLAT (no trade).
    Returns integer class predictions (0=DOWN, 1=FLAT, 2=UP).
    """
    edge = probs[:, UP] - probs[:, DOWN]
    return np.where(edge >= margin, UP, np.where(edge <= -margin, DOWN, FLAT)).astype(int)


def evaluate_from_probs(
    probs: np.ndarray,
    labels: np.ndarray,
    margin: float = 0.0,
    fwd_rets: np.ndarray | None = None,
    dates: np.ndarray | None = None,
    ticker_idxs: np.ndarray | None = None,
) -> dict[str, Any]:
    """Compute all evaluation metrics from class probabilities + labels.

    Args:
        probs: (N, n_classes) class probabilities.
        labels: (N,) true class labels.
        margin: Abstention margin (0.0 = always trade on argmax edge).
        fwd_rets: (N,) actual forward log returns per window (for real Sharpe).
        dates: (N,) window end dates (datetime64).
        ticker_idxs: (N,) ticker indices per window.
    """
    preds = apply_margin_rule(probs, margin)

    accuracy = float((preds == labels).mean())
    coverage = float((preds != FLAT).mean())

    per_class_f1 = _compute_per_class_f1(labels, preds, n_classes=ML_CONFIG.N_CLASSES)
    confusion_matrix = _compute_confusion_matrix(labels, preds, n_classes=ML_CONFIG.N_CLASSES)

    directional_mask = labels != FLAT
    n_directional = int(directional_mask.sum())
    if n_directional > 0:
        n_directional_correct = int((preds[directional_mask] == labels[directional_mask]).sum())
        directional_acc = float(n_directional_correct / n_directional)
    else:
        n_directional_correct = 0
        directional_acc = 0.0

    if fwd_rets is not None and dates is not None and ticker_idxs is not None:
        sharpe = _real_sharpe_metrics(preds, fwd_rets, dates, ticker_idxs)
    else:
        sharpe = {
            "sharpe_long_only_0bps": None,
            "sharpe_long_only_10bps": None,
            "sharpe_long_short_0bps": None,
            "sharpe_long_short_10bps": None,
        }

    return {
        "accuracy": accuracy,
        "coverage": coverage,
        "directional_accuracy": directional_acc,
        "n_directional": n_directional,
        "n_directional_correct": n_directional_correct,
        "per_class_f1": per_class_f1,
        "confusion_matrix": confusion_matrix.tolist(),
        "margin": float(margin),
        "total_samples": len(labels),
        **sharpe,
    }


@torch.no_grad()
def evaluate(
    model: GlobalLSTM,
    dataloader: DataLoader,
    device: torch.device,
    margin: float = 0.0,
    fwd_rets: np.ndarray | None = None,
    dates: np.ndarray | None = None,
    ticker_idxs: np.ndarray | None = None,
) -> dict[str, Any]:
    """Evaluate a model on a DataLoader (unshuffled).

    Convenience wrapper around predict_probs + evaluate_from_probs for
    callers that have no precomputed probabilities (e.g. HPO test eval).
    """
    probs, labels = predict_probs(model, dataloader, device)
    return evaluate_from_probs(
        probs, labels, margin=margin, fwd_rets=fwd_rets, dates=dates, ticker_idxs=ticker_idxs
    )


def sweep_margin(
    probs: np.ndarray,
    labels: np.ndarray,
    fwd_rets: np.ndarray,
    dates: np.ndarray,
    ticker_idxs: np.ndarray,
) -> tuple[float, list[dict[str, float]]]:
    """Sweep the abstention margin on validation data.

    Selects the margin maximising the cost-free long-short Sharpe on val
    (the same metric the model is judged on at test time). Never touch test.

    A minimum-coverage guard (MARGIN_MIN_COVERAGE of windows must stay
    active) prevents the degenerate solution where a huge margin "wins"
    by barely trading at all — a near-empty portfolio's Sharpe is noise.

    Returns:
        (best_margin, full_curve) where curve is a list of
        {"margin", "sharpe_long_short_0bps"} dicts.
    """
    best_margin = 0.0
    best_sharpe = -np.inf
    curve: list[dict[str, float]] = []
    n = len(probs)

    for m in np.arange(ML_CONFIG.MARGIN_MIN, ML_CONFIG.MARGIN_MAX + 1e-9, ML_CONFIG.MARGIN_STEP):
        m = float(m)
        preds = apply_margin_rule(probs, m)
        sharpe = _strategy_sharpe(
            preds, fwd_rets, dates, ticker_idxs, mode="long_short", cost_bps=0.0
        )
        coverage = float((preds != 1).mean()) if n else 0.0
        curve.append({"margin": round(m, 3), "sharpe_long_short_0bps": sharpe})
        if coverage < ML_CONFIG.MARGIN_MIN_COVERAGE:
            continue  # degenerate: too few active positions to trust the Sharpe
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_margin = m

    return best_margin, curve


def _real_sharpe_metrics(
    preds: np.ndarray,
    fwd_rets: np.ndarray,
    dates: np.ndarray,
    ticker_idxs: np.ndarray,
) -> dict[str, float | None]:
    """Sharpe ratios from actual forward log returns.

    Reports long-only and long-short, each at 0 cost and at
    ML_CONFIG.COST_BPS_ROUND_TRIP charged once per active position.
    """
    out: dict[str, float | None] = {}
    for mode in ("long_only", "long_short"):
        for cost in (0.0, ML_CONFIG.COST_BPS_ROUND_TRIP):
            key = f"sharpe_{mode}_{int(cost)}bps"
            try:
                out[key] = _strategy_sharpe(
                    preds, fwd_rets, dates, ticker_idxs, mode=mode, cost_bps=cost
                )
            except Exception as e:  # noqa: BLE001 - eval must not crash training
                logger.warning("Sharpe computation failed (%s): %s", key, e)
                out[key] = None
    return out


def _strategy_sharpe(
    preds: np.ndarray,
    fwd_rets: np.ndarray,
    dates: np.ndarray,
    ticker_idxs: np.ndarray,
    mode: str,
    cost_bps: float,
) -> float:
    """Annualised Sharpe of the strategy implied by `preds` on real returns.

    Portfolio construction:
      1. Per ticker keep only NON-OVERLAPPING windows (every
         FORECAST_HORIZON-th window in date order) — overlapping h-day
         returns would inflate the sample count by ~h.
      2. Equal-weight all windows that end on the same date (cross-sectional
         portfolio return for that date).
      3. Keep every FORECAST_HORIZON-th portfolio date so annualisation
         (sqrt(252/h) periods per year) uses genuinely non-overlapping
         holding periods.

    Cost: `cost_bps` round-trip charged once per active position.
    """
    h = ML_CONFIG.FORECAST_HORIZON

    if mode == "long_only":
        signal = (preds == UP).astype(float)
    else:
        signal = np.where(preds == UP, 1.0, np.where(preds == DOWN, -1.0, 0.0))

    keep = np.zeros(len(preds), dtype=bool)
    for t in np.unique(ticker_idxs):
        idx = np.flatnonzero(ticker_idxs == t)
        keep[idx[::h]] = True

    sig = signal[keep]
    rets = fwd_rets[keep]
    dts = dates[keep]

    active = sig != 0.0
    gross = sig * rets
    gross[active] -= cost_bps / 1e4

    unique_dates, inv = np.unique(dts, return_inverse=True)
    counts = np.bincount(inv)
    sums = np.bincount(inv, weights=gross)
    port = sums / np.maximum(counts, 1)

    port = port[::h]

    if len(port) < 2:
        return 0.0
    std = float(port.std())
    if std == 0.0:
        return 0.0
    return float(port.mean() / std * np.sqrt(252.0 / h))


def _compute_per_class_f1(
    labels: np.ndarray,
    preds: np.ndarray,
    n_classes: int = 3,
) -> dict[str, float]:
    """Compute per-class F1 score.

    Uses sklearn.metrics.f1_score.

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
