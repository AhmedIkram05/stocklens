"""
Training loop for GlobalLSTM.

Key features:
    - AdamW optimiser with weight decay
    - Focal loss with class weights (handles imbalance + focuses on hard directional samples)
    - Cosine annealing LR scheduler
    - Early stopping on validation DIRECTIONAL accuracy (not loss — loss never improves
      because the label SNR is low, but directional accuracy provides a useful signal)
    - Per-epoch logging of loss, accuracy, and directional accuracy
"""

from __future__ import annotations

import logging
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F
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
    weights[~torch.isfinite(weights)] = 1.0
    return weights


class FocalLoss(nn.Module):
    """Focal Loss with class weights.

    FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)

    The (1-p_t)^gamma term down-weights well-classified examples (the majority
    FLAT class), forcing the model to focus on hard directional (UP/DOWN)
    samples. Gamma=2.0 is the standard value from the RetinaNet paper.

    Unlike the previous FocalLoss attempt that created a gradient dead zone
    (it was combined with AsymmetricCost), this standalone implementation
    uses the standard formulation with alpha=class_weights for class imbalance
    and gamma=2.0 for hard-example focusing.
    """

    def __init__(self, alpha: torch.Tensor | None = None, gamma: float = 2.0) -> None:
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce_loss = F.cross_entropy(logits, targets, reduction="none", weight=self.alpha)
        pt = torch.exp(-ce_loss)
        focal_loss = ((1 - pt) ** self.gamma * ce_loss).mean()
        return focal_loss


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
        criterion: Loss function (FocalLoss or CrossEntropyLoss).
        optimizer: AdamW optimizer.
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
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
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
) -> tuple[float, float, float]:
    """Validate the model.

    Returns loss, overall accuracy, and directional accuracy.
    Directional accuracy = accuracy on UP/DOWN labels only (ignoring FLAT).
    This is the primary metric for early stopping since val_loss is flat
    on noisy financial data.

    Args:
        model: GlobalLSTM instance.
        dataloader: Validation DataLoader.
        criterion: Loss function.
        device: torch.device.

    Returns:
        (validation_loss, accuracy, directional_accuracy) tuple.
    """
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    dir_correct = 0
    dir_total = 0

    for features, labels, ticker_idxs in dataloader:
        features = features.to(device)
        labels = labels.to(device)
        ticker_idxs = ticker_idxs.to(device)

        logits = model(features, ticker_idxs)
        loss = criterion(logits, labels)
        total_loss += loss.item()

        preds = logits.argmax(dim=-1)

        # Overall accuracy
        correct += (preds == labels).sum().item()
        total += labels.size(0)

        # Directional accuracy (UP/DOWN only, excluding FLAT)
        dir_mask = labels != 1
        dir_correct += ((preds == labels) & dir_mask).sum().item()
        dir_total += dir_mask.sum().item()

    avg_loss = total_loss / max(len(dataloader), 1)
    accuracy = correct / max(total, 1)
    dir_accuracy = dir_correct / max(dir_total, 1)

    return avg_loss, accuracy, dir_accuracy


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
    """Full training loop with early stopping on directional accuracy.

    Early stopping monitors *directional accuracy* (UP/DOWN only) instead of
    validation loss. On noisy financial data, validation loss is essentially
    flat throughout training because the model can never escape the prior.
    Directional accuracy, while also noisy, provides a useful signal for
    model selection.

    Args:
        model: GlobalLSTM instance.
        train_loader: Training DataLoader.
        val_loader: Validation DataLoader.
        n_epochs: Maximum number of epochs.
        lr: Learning rate.
        weight_decay: AdamW weight decay.
        patience: Early stopping patience.
        min_delta: Minimum directional accuracy improvement.
        device: Target device. Auto-detected if None.

    Returns:
        Dict with keys: train_losses, val_losses, val_accuracies,
        val_directional_accuracies, best_epoch.
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

    # Focal Loss with class weights — focuses on hard directional samples
    # instead of letting well-classified FLAT samples dominate the gradient.
    # Gamma=2.0 down-weights easy examples; alpha handles class imbalance.
    criterion = FocalLoss(alpha=class_weights, gamma=ML_CONFIG.FOCAL_GAMMA).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=lr,
        weight_decay=weight_decay,
    )

    # Cosine annealing LR — starts at lr and decays to 0 over n_epochs.
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    history: dict[str, Any] = {
        "train_losses": [],
        "val_losses": [],
        "val_accuracies": [],
        "val_directional_accuracies": [],
        "learning_rates": [],
    }

    # Early stopping on directional accuracy
    best_dir_acc = 0.0
    best_epoch = -1
    patience_counter = 0
    best_state = None

    for epoch in range(1, n_epochs + 1):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc, val_dir_acc = validate(model, val_loader, criterion, device)

        history["train_losses"].append(train_loss)
        history["val_losses"].append(val_loss)
        history["val_accuracies"].append(val_acc)
        history["val_directional_accuracies"].append(val_dir_acc)
        history["learning_rates"].append(scheduler.get_last_lr()[0])

        logger.info(
            "Epoch %d/%d - train_loss: %.4f, val_loss: %.4f, val_acc: %.4f, "
            "val_dir_acc: %.4f, lr: %.6f",
            epoch,
            n_epochs,
            train_loss,
            val_loss,
            val_acc,
            val_dir_acc,
            scheduler.get_last_lr()[0],
        )

        scheduler.step()

        # Early stopping on directional accuracy
        if val_dir_acc > best_dir_acc + min_delta:
            best_dir_acc = val_dir_acc
            best_epoch = epoch
            patience_counter = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            logger.info("New best val_dir_acc: %.4f at epoch %d", val_dir_acc, epoch)
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info(
                    "Early stopping at epoch %d (best epoch %d, val_dir_acc %.4f)",
                    epoch,
                    best_epoch,
                    best_dir_acc,
                )
                break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
    model.to(device)

    history["best_epoch"] = best_epoch
    history["best_dir_acc"] = best_dir_acc
    return history
