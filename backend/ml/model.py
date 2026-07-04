"""
GlobalLSTM - multi-ticker LSTM model with entity embeddings.

Architecture:
    TickerEmbedding(vocab_size, embed_dim=16) -> concat with features
    -> FeatureProjection(n_features + embed_dim, hidden_dim)
    -> LSTM(hidden_dim, hidden_size=128, num_layers=2, dropout=0.3, batch_first=True)
    -> Classifier(128, 3) -> softmax

The model learns per-ticker embedding vectors to capture ticker-specific
price dynamics while sharing LSTM weights across all tickers.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class GlobalLSTM(nn.Module):
    """Global multi-ticker LSTM with entity embeddings.

    Args:
        n_features: Number of technical indicator features per time step.
        vocab_size: Number of tickers in vocabulary (including UNK).
        embed_dim: Entity embedding dimension.
        hidden_dim: LSTM hidden state dimension.
        n_layers: Number of LSTM layers.
        dropout: Dropout probability (applied between LSTM layers and after LSTM).
        n_classes: Number of output classes (default 3: DOWN, FLAT, UP).
        unk_idx: Index reserved for unknown tickers (default 0).
    """

    def __init__(
        self,
        n_features: int,
        vocab_size: int,
        embed_dim: int = 16,
        hidden_dim: int = 128,
        n_layers: int = 2,
        dropout: float = 0.3,
        n_classes: int = 3,
        unk_idx: int = 0,
    ) -> None:
        super().__init__()

        self.n_features = n_features
        self.embed_dim = embed_dim
        self.hidden_dim = hidden_dim
        self.unk_idx = unk_idx

        # Inference metadata (set by load() from checkpoint)
        self._vocab: dict[str, int] = {}
        self._feature_means: Optional[np.ndarray] = None
        self._feature_stds: Optional[np.ndarray] = None
        self._model_version: str = "0"

        # Ticker entity embedding
        self.ticker_embedding = nn.Embedding(
            num_embeddings=vocab_size,
            embedding_dim=embed_dim,
            padding_idx=unk_idx,
        )

        # Project concatenated features + embedding to hidden_dim
        input_size = n_features + embed_dim
        self.feature_projection = nn.Linear(input_size, hidden_dim)

        # LSTM
        self.lstm = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=hidden_dim,
            num_layers=n_layers,
            dropout=dropout if n_layers > 1 else 0.0,
            batch_first=True,
            bidirectional=False,
        )

        # Post-LSTM dropout
        self.dropout = nn.Dropout(dropout)

        # Classifier
        self.classifier = nn.Linear(hidden_dim, n_classes)

    def forward(
        self,
        features: torch.Tensor,
        ticker_idxs: torch.Tensor,
    ) -> torch.Tensor:
        """Forward pass.

        Args:
            features: (batch_size, seq_len, n_features) tensor.
            ticker_idxs: (batch_size,) tensor of ticker embedding indices.

        Returns:
            (batch_size, n_classes) logits (NOT softmaxed - use with CrossEntropyLoss).
        """
        batch_size, seq_len, _ = features.shape

        # Clamp ticker indices to valid range (handles OOV at inference)
        ticker_idxs = ticker_idxs.clamp(0, self.ticker_embedding.num_embeddings - 1)

        # Get ticker embeddings: (batch_size, embed_dim)
        ticker_embeds = self.ticker_embedding(ticker_idxs)  # (B, embed_dim)

        # Expand to match sequence length: (batch_size, seq_len, embed_dim)
        ticker_embeds = ticker_embeds.unsqueeze(1).expand(-1, seq_len, -1)

        # Concatenate features with ticker embedding
        combined = torch.cat([features, ticker_embeds], dim=-1)

        # Project to hidden_dim
        projected = self.feature_projection(combined)  # (B, seq_len, hidden_dim)
        projected = F.relu(projected)

        # LSTM
        lstm_out, (h_n, _) = self.lstm(projected)  # lstm_out: (B, seq_len, hidden_dim)

        # Use the last hidden state from the top LSTM layer
        # h_n shape: (n_layers, B, hidden_dim) -> take last layer
        last_hidden = h_n[-1]  # (B, hidden_dim)

        # Dropout + classifier
        last_hidden = self.dropout(last_hidden)
        logits = self.classifier(last_hidden)  # (B, n_classes)

        return logits

    @torch.no_grad()
    def predict_proba(self, features: torch.Tensor, ticker_idxs: torch.Tensor) -> torch.Tensor:
        """Return softmax probabilities.

        Args:
            features: (batch_size, seq_len, n_features) tensor.
            ticker_idxs: (batch_size,) tensor.

        Returns:
            (batch_size, n_classes) probability tensor.
        """
        logits = self.forward(features, ticker_idxs)
        return F.softmax(logits, dim=-1)

    def save(
        self,
        path: str,
        vocab: Optional[dict[str, int]] = None,
        feature_means: Optional[np.ndarray] = None,
        feature_stds: Optional[np.ndarray] = None,
        model_version: str = "0",
    ) -> None:
        """Save model state dict and config metadata.

        Args:
            path: Path to save the .pt file.
            vocab: Ticker-to-index vocabulary for embedding lookup at inference.
            feature_means: Per-feature means for z-score standardisation (inverse of training).
            feature_stds: Per-feature stds for z-score standardisation.
            model_version: Model version string (default "0").
        """
        payload: dict = {
            "state_dict": self.state_dict(),
            "n_features": self.n_features,
            "embed_dim": self.ticker_embedding.embedding_dim,
            "hidden_dim": self.hidden_dim,
            "n_layers": self.lstm.num_layers,
            "dropout": self.dropout.p,
            "n_classes": self.classifier.out_features,
            "vocab_size": self.ticker_embedding.num_embeddings,
            "unk_idx": self.unk_idx,
            "model_version": model_version,
        }
        if vocab is not None:
            payload["vocab"] = vocab
        if feature_means is not None:
            payload["feature_means"] = feature_means
        if feature_stds is not None:
            payload["feature_stds"] = feature_stds
        torch.save(payload, path)

    @classmethod
    def load(cls, path: str, device: torch.device | None = None) -> GlobalLSTM:
        """Load model from saved state dict.

        Args:
            path: Path to the .pt file.
            device: Target device. If None, uses saved tensor's device.

        Returns:
            Loaded GlobalLSTM instance with ``vocab``, ``feature_means``,
            ``feature_stds``, ``model_version`` attributes set if present in checkpoint.
        """
        # ponytail: weights_only=False because checkpoint includes numpy arrays
        # from optional metadata (vocab, feature_means, feature_stds). Since we
        # only load checkpoints we saved ourselves (internal pipeline), this is safe.
        checkpoint = torch.load(path, map_location=device, weights_only=False)
        model = cls(
            n_features=checkpoint["n_features"],
            vocab_size=checkpoint["vocab_size"],
            embed_dim=checkpoint["embed_dim"],
            hidden_dim=checkpoint["hidden_dim"],
            n_layers=checkpoint["n_layers"],
            dropout=checkpoint["dropout"],
            n_classes=checkpoint["n_classes"],
            unk_idx=checkpoint["unk_idx"],
        )
        model.load_state_dict(checkpoint["state_dict"])

        # Load optional metadata for inference standardisation
        model._vocab = checkpoint.get("vocab", {})
        model._feature_means = checkpoint.get("feature_means")
        model._feature_stds = checkpoint.get("feature_stds")
        model._model_version = checkpoint.get("model_version", "0")

        model.eval()
        return model
