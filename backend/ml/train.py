"""
Training loop for GlobalLSTM.

Key features:
    - Adam optimiser with weight decay
    - Weighted cross-entropy loss (handles class imbalance)
    - Early stopping with patience 10
    - Per-epoch logging of loss and accuracy
"""

from __future__ import annotations

import logging
from typing import Any

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)


def compute_class_weights(labels: torch.Tensor, n_classes: int = 3) -> torch.Tensor:
    """Compute class weights inversely proportional to class frequencies.

    weight[c] = total_samples / (n_classes * samples_in_class[c])

    Args:
        labels: (N,) tensor of class labels.
        n_classes: Number of classes.

    Returns:
        (n_classes,) tensor of class weights.
    """
    class_counts = torch.bincount(labels, minlength=n_classes).float()
    total = class_counts.sum()
    weights = total / (n_classes * class_counts)
    # Replace inf (empty class) with 1.0
    weights[~torch.isfinite(weights)] = 1.0
    return weights


def train_epoch(
    model: GlobalLSTM,
    dataloader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    """Train for one epoch.

    Args:
        model: GlobalLSTM instance.
        dataloader: Training DataLoader.
        criterion: Loss function (weighted cross-entropy).
        optimizer: Adam optimizer.
        device: torch.device.

    Returns:
        Mean training loss for the epoch.
    """
    model.train()
    total_loss = 0.0
    num_batches = 0

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        labels = labels.to(device)
        ticker_idxs = ticker_idxs.to(device)

        optimizer.zero_grad()
        logits = model(features, ticker_idxs)
        loss = criterion(logits, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item()
        num_batches += 1

    return total_loss / max(num_batches, 1)


@torch.no_grad()
def validate(
    model: GlobalLSTM,
    dataloader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    """Validate the model.

    Args:
        model: GlobalLSTM instance.
        dataloader: Validation DataLoader.
        criterion: Loss function.
        device: torch.device.

    Returns:
        (validation_loss, accuracy) tuple.
    """
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        labels = labels.to(device)
        ticker_idxs = ticker_idxs.to(device)

        logits = model(features, ticker_idxs)
        loss = criterion(logits, labels)
        total_loss += loss.item()

        preds = logits.argmax(dim=-1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    avg_loss = total_loss / max(len(dataloader), 1)
    accuracy = correct / max(total, 1)
    return avg_loss, accuracy


def train(
    model: GlobalLSTM,
    train_loader: DataLoader,
    val_loader: DataLoader,
    n_epochs: int = ML_CONFIG.EPOCHS,
    lr: float = ML_CONFIG.LEARNING_RATE,
    weight_decay: float = ML_CONFIG.WEIGHT_DECAY,
    patience: int = ML_CONFIG.PATIENCE,
    min_delta: float = ML_CONFIG.MIN_DELTA,
    device: torch.device | None = None,
) -> dict[str, list[float]]:
    """Full training loop with early stopping.

    Args:
        model: GlobalLSTM instance.
        train_loader: Training DataLoader.
        val_loader: Validation DataLoader.
        n_epochs: Maximum number of epochs.
        lr: Learning rate.
        weight_decay: AdamW weight decay.
        patience: Early stopping patience.
        min_delta: Minimum validation loss improvement.
        device: Target device. Auto-detected if None.

    Returns:
        Dict with keys: train_losses, val_losses, val_accuracies, best_epoch.
    """
    if device is None:
        from ml.utils import get_device

        device = get_device()

    model = model.to(device)

    # Compute class weights from training data
    all_labels = []
    for _, labels, _ in train_loader:
        all_labels.append(labels)
    train_labels = torch.cat(all_labels)
    class_weights = compute_class_weights(train_labels).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=lr,
        weight_decay=weight_decay,
    )

    history: dict[str, Any] = {
        "train_losses": [],
        "val_losses": [],
        "val_accuracies": [],
    }

    best_val_loss = float("inf")
    best_epoch = -1
    patience_counter = 0
    best_state = None

    for epoch in range(1, n_epochs + 1):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = validate(model, val_loader, criterion, device)

        history["train_losses"].append(train_loss)
        history["val_losses"].append(val_loss)
        history["val_accuracies"].append(val_acc)

        logger.info(
            "Epoch %d/%d - train_loss: %.4f, val_loss: %.4f, val_acc: %.4f",
            epoch,
            n_epochs,
            train_loss,
            val_loss,
            val_acc,
        )

        # Early stopping check
        if val_loss < best_val_loss - min_delta:
            best_val_loss = val_loss
            best_epoch = epoch
            patience_counter = 0
            # Save best model state
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info(
                    "Early stopping at epoch %d (best epoch %d, val_loss %.4f)",
                    epoch,
                    best_epoch,
                    best_val_loss,
                )
                break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
    model.to(device)

    history["best_epoch"] = best_epoch
    return history
