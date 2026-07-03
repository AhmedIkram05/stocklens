"""Tests for ml/model.py - GlobalLSTM architecture."""

from __future__ import annotations

import tempfile

import pytest
import torch


@pytest.fixture
def model() -> torch.nn.Module:
    from ml.model import GlobalLSTM

    return GlobalLSTM(
        n_features=13,
        vocab_size=56,  # 55 tickers + UNK
        embed_dim=16,
        hidden_dim=128,
        n_layers=2,
        dropout=0.3,
        n_classes=3,
        unk_idx=0,
    )


class TestGlobalLSTM:
    def test_forward_shape(self, model: torch.nn.Module) -> None:
        batch_size, seq_len = 32, 30
        features = torch.randn(batch_size, seq_len, 13)
        ticker_idxs = torch.zeros(batch_size, dtype=torch.long)

        logits = model(features, ticker_idxs)
        assert logits.shape == (batch_size, 3)

    def test_predict_proba(self, model: torch.nn.Module) -> None:
        features = torch.randn(16, 30, 13)
        ticker_idxs = torch.zeros(16, dtype=torch.long)

        probs = model.predict_proba(features, ticker_idxs)
        assert probs.shape == (16, 3)
        # Probabilities should sum to 1
        assert torch.allclose(probs.sum(dim=-1), torch.ones(16))

    def test_different_ticker_embeddings(self) -> None:
        from ml.model import GlobalLSTM

        model = GlobalLSTM(
            n_features=13,
            vocab_size=10,
            embed_dim=8,
            hidden_dim=32,
            n_layers=1,
            dropout=0.0,
            n_classes=3,
        )

        features = torch.randn(4, 30, 13)
        ticker_idxs = torch.tensor([0, 1, 2, 3])

        logits = model(features, ticker_idxs)
        # Different tickers should produce different outputs (different embeddings)
        assert not torch.allclose(logits[0], logits[1])

    def test_forward_out_of_vocab_index(self, model: torch.nn.Module) -> None:
        """Out-of-vocab indices are handled by the embedding layer's clamping."""
        features = torch.randn(2, 30, 13)
        ticker_idxs = torch.tensor([0, 999])  # UNK and out-of-vocab index

        logits = model(features, ticker_idxs)
        assert logits.shape == (2, 3)

    def test_save_and_load(self, model: torch.nn.Module) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pt") as f:
            model.save(f.name)

            loaded = model.__class__.load(f.name)
            assert isinstance(loaded, model.__class__)
            assert loaded.n_features == 13
            assert loaded.hidden_dim == 128

            # Forward pass should work on loaded model
            features = torch.randn(8, 30, 13)
            ticker_idxs = torch.zeros(8, dtype=torch.long)
            logits = loaded(features, ticker_idxs)
            assert logits.shape == (8, 3)

    def test_save_with_metadata(self, model: torch.nn.Module) -> None:
        """Save and load with vocab and standardisation metadata."""
        import numpy as np

        with tempfile.NamedTemporaryFile(suffix=".pt") as f:
            vocab = {"AAPL": 1, "MSFT": 2, "<UNK>": 0}
            feature_means = np.zeros(13)
            feature_stds = np.ones(13)
            model.save(f.name, vocab=vocab, feature_means=feature_means, feature_stds=feature_stds)

            loaded = model.__class__.load(f.name)
            assert loaded._vocab == vocab
            assert loaded._feature_means is not None
            assert loaded._feature_stds is not None

    def test_single_sample(self, model: torch.nn.Module) -> None:
        features = torch.randn(1, 30, 13)
        ticker_idxs = torch.zeros(1, dtype=torch.long)

        logits = model(features, ticker_idxs)
        assert logits.shape == (1, 3)
        assert not torch.isnan(logits).any()

    def test_gradient_flow(self, model: torch.nn.Module) -> None:
        features = torch.randn(16, 30, 13, requires_grad=True)
        ticker_idxs = torch.zeros(16, dtype=torch.long)

        logits = model(features, ticker_idxs)
        loss = logits.sum()
        loss.backward()

        # All parameters should have gradients
        for name, param in model.named_parameters():
            assert param.grad is not None, f"No gradient for {name}"
