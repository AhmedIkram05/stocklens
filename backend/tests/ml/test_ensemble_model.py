"""Tests for the registry-side seed ensemble wrapper."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ml.ensemble_model import GlobalLSTMEnsemble
from ml.model import GlobalLSTM


def _save_member(path, seed: int) -> GlobalLSTM:
    model = GlobalLSTM(
        n_features=17,
        vocab_size=2,
        embed_dim=4,
        hidden_dim=8,
        n_layers=1,
        dropout=0.0,
        n_classes=3,
        unk_idx=0,
    )
    model.save(
        str(path / f"model_seed{seed}.pt"),
        vocab={"<UNK>": 0, "AAPL": 1},
        feature_means=np.zeros(17),
        feature_stds=np.ones(17),
        margin=0.1,
        ensemble_size=2,
    )
    return model


def test_loads_every_member_and_averages(tmp_path):
    _save_member(tmp_path, 0)
    _save_member(tmp_path, 1)
    ensemble = GlobalLSTMEnsemble(member_count=2)
    ensemble.load_context(SimpleNamespace(artifacts={"members": str(tmp_path)}))

    frame = pd.DataFrame(
        {
            "features": [np.zeros((30, 17), dtype=np.float32)],
            "ticker_idx": [1],
        }
    )
    probs = ensemble.predict(None, frame)
    assert probs.shape == (1, 3)
    np.testing.assert_allclose(probs.sum(axis=1), 1.0, rtol=1e-5)


def test_rejects_partial_ensemble(tmp_path):
    _save_member(tmp_path, 0)
    ensemble = GlobalLSTMEnsemble(member_count=2)
    with pytest.raises(ValueError, match="member count mismatch"):
        ensemble.load_context(SimpleNamespace(artifacts={"members": str(tmp_path)}))
