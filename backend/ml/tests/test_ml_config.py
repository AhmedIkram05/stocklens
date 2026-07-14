"""
Tests for MLConfig dataclass.

All tests are pure Python with no DB or MLflow dependency.
"""

from __future__ import annotations

import dataclasses

import pytest

from ml.config import MLConfig


def test_defaults_are_set() -> None:
    """All core fields have sensible defaults."""
    cfg = MLConfig()
    assert cfg.SEQUENCE_LENGTH == 30
    assert cfg.N_FEATURES == 17
    assert cfg.EMBED_DIM == 16
    assert cfg.HIDDEN_DIM == 80
    assert cfg.N_LAYERS == 2
    assert cfg.N_CLASSES == 3
    assert cfg.EPOCHS == 100
    assert cfg.BATCH_SIZE == 256
    assert cfg.PATIENCE == 15


def test_frozen_immutable() -> None:
    """MLConfig is frozen — attribute assignment raises TypeError."""
    cfg = MLConfig()
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        cfg.SEQUENCE_LENGTH = 60  # type: ignore[misc]


def test_splits_sum_to_one() -> None:
    """Train/val/test split fractions sum to 1.0."""
    cfg = MLConfig()
    assert cfg.TRAIN_SPLIT + cfg.VAL_SPLIT + cfg.TEST_SPLIT == pytest.approx(1.0)


def test_sync_database_url_strips_asyncpg() -> None:
    """SYNC_DATABASE_URL removes the +asyncpg suffix."""
    cfg = MLConfig()
    assert "+asyncpg" not in cfg.SYNC_DATABASE_URL
    assert cfg.SYNC_DATABASE_URL.startswith("postgresql://")


def test_hyperparameter_ranges_positive() -> None:
    """All numeric hyperparameter fields are positive."""
    cfg = MLConfig()
    for name in [
        "SEQUENCE_LENGTH",
        "N_FEATURES",
        "EMBED_DIM",
        "HIDDEN_DIM",
        "N_LAYERS",
        "N_CLASSES",
        "EPOCHS",
        "BATCH_SIZE",
        "PATIENCE",
        "VOL_LOOKBACK",
        "FORECAST_HORIZON",
        "OHLCV_YEARS",
        "MIN_OHLCV_DAYS",
        "PREDICTION_CACHE_TTL",
    ]:
        val = getattr(cfg, name)
        assert isinstance(val, int), f"{name} should be int, got {type(val)}"
        assert val > 0, f"{name}={val} should be positive"

    for name in [
        "LEARNING_RATE",
        "WEIGHT_DECAY",
        "DROPOUT",
        "FOCAL_GAMMA",
        "THRESHOLD_MULT",
        "MIN_DELTA",
        "TRAIN_SPLIT",
        "VAL_SPLIT",
        "TEST_SPLIT",
        "VOL_FILTER_PERCENTILE",
    ]:
        val = getattr(cfg, name)
        assert isinstance(val, float), f"{name} should be float, got {type(val)}"
        assert val > 0, f"{name}={val} should be positive"


def test_split_fractions_are_float() -> None:
    """Split fractions are proper floats in (0, 1)."""
    cfg = MLConfig()
    for name in ["TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT"]:
        val = getattr(cfg, name)
        assert 0 < val < 1


def test_class_names_tuple() -> None:
    """CLASS_NAMES is a tuple of three strings."""
    cfg = MLConfig()
    assert cfg.CLASS_NAMES == ("DOWN", "FLAT", "UP")


def test_training_tickers_is_list_of_strings() -> None:
    """TRAINING_TICKERS is a non-empty list of strings."""
    cfg = MLConfig()
    assert isinstance(cfg.TRAINING_TICKERS, list)
    assert len(cfg.TRAINING_TICKERS) > 0
    assert all(isinstance(t, str) for t in cfg.TRAINING_TICKERS)
