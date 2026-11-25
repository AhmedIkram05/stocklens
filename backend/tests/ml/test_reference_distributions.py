"""
Tests for reference distribution building, DB storage, and filesystem fallback.

Tests that need DB mocking use AsyncMock for asyncpg.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from ml.reference_distributions import (
    build_reference_from_training_data,
    load_reference_from_db,
    store_reference_in_db,
)

# ---------------------------------------------------------------------------
# build_reference_from_training_data
# ---------------------------------------------------------------------------


def _make_3d_data(
    n: int = 100,
    seq_len: int = 30,
    n_feat: int = 17,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    features = rng.normal(0, 1, (n, seq_len, n_feat)).astype(np.float32)
    labels = np.array([0] * 40 + [1] * 30 + [2] * 30)
    return features, labels


def test_build_reference_3d_input() -> None:
    """3D input (N, 30, 17) is flattened correctly."""
    features, labels = _make_3d_data(n=100)
    ref = build_reference_from_training_data(features, labels)
    assert ref["n_training_samples"] == 100 * 30
    assert ref["n_features"] == 17
    assert len(ref["feature_histograms"]) == 17


def test_build_reference_2d_input() -> None:
    """2D input (N, 17) is handled without flattening."""
    rng = np.random.default_rng(42)
    features = rng.normal(0, 1, (100, 17)).astype(np.float32)
    labels = np.array([0] * 40 + [1] * 30 + [2] * 30)
    ref = build_reference_from_training_data(features, labels)
    assert ref["n_training_samples"] == 100
    assert ref["n_features"] == 17


def test_build_reference_prediction_distribution() -> None:
    """Class proportions are computed correctly."""
    features, labels = _make_3d_data(n=100)
    labels[:50] = 0
    labels[50:75] = 1
    labels[75:] = 2
    ref = build_reference_from_training_data(features, labels)
    dist = ref["prediction_distribution"]
    assert len(dist) == 3
    assert sum(dist) == pytest.approx(1.0)
    # 50/100 = 0.5 for class 0, 25/100 = 0.25 for classes 1 and 2
    assert dist[0] > dist[1]


def test_build_reference_custom_feature_names() -> None:
    """Custom feature names are used when provided."""
    features, labels = _make_3d_data(n=50, n_feat=3)
    names = ["feat_a", "feat_b", "feat_c"]
    ref = build_reference_from_training_data(features, labels, feature_names=names)
    assert ref["feature_names"] == names
    assert "feat_a" in ref["feature_histograms"]
    assert "feat_b" in ref["feature_histograms"]


def test_build_reference_histogram_structure() -> None:
    """Each feature histogram has the expected keys and types."""
    features, labels = _make_3d_data(n=50, n_feat=2)
    ref = build_reference_from_training_data(features, labels, feature_names=["a", "b"])
    h = ref["feature_histograms"]["a"]
    assert sorted(h.keys()) == ["bin_edges", "histogram", "n", "values"]
    assert len(h["histogram"]) == 20
    assert len(h["bin_edges"]) == 21
    assert isinstance(h["n"], int)
    assert h["n"] > 0


def test_build_reference_values_sampled() -> None:
    """Values array is sampled to at most 1000 entries."""
    features, labels = _make_3d_data(n=1000, seq_len=1, n_feat=1)
    ref = build_reference_from_training_data(features, labels, feature_names=["x"])
    assert len(ref["feature_histograms"]["x"]["values"]) <= 1000


def test_build_reference_empty_features() -> None:
    """Empty feature array returns empty reference."""
    features = np.empty((0, 17), dtype=np.float32)
    labels = np.empty((0,), dtype=np.int64)
    ref = build_reference_from_training_data(features, labels)
    assert ref["n_training_samples"] == 0
    assert ref["n_features"] == 0
    assert ref["feature_histograms"] == {}


def test_build_reference_all_nan_returns_empty() -> None:
    """All-NaN features return empty reference."""
    features = np.full((50, 17), np.nan, dtype=np.float32)
    labels = np.zeros(50, dtype=np.int64)
    ref = build_reference_from_training_data(features, labels)
    assert ref["n_training_samples"] == 0


# ---------------------------------------------------------------------------
# store_reference_in_db / load_reference_from_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_reference_in_db() -> None:
    """store_reference_in_db executes the correct UPDATE."""
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()

    ref = {
        "feature_histograms": {},
        "prediction_distribution": [0.4, 0.3, 0.3],
        "n_training_samples": 100,
    }

    await store_reference_in_db(fake_conn, ref, model_version="v3")
    fake_conn.execute.assert_called_once()
    call_args = fake_conn.execute.call_args
    assert call_args is not None
    sql = call_args[0][0]
    assert "UPDATE model_registry" in sql
    assert "jsonb_set" in sql


@pytest.mark.asyncio
async def test_load_reference_from_db_found() -> None:
    """load_reference_from_db returns reference when champion exists."""
    fake_row = MagicMock()
    fake_row.__getitem__.side_effect = lambda k: {
        "metrics": {
            "reference_distributions": {
                "feature_histograms": {"ma_5": {"n": 100}},
                "prediction_distribution": [0.4, 0.3, 0.3],
            },
        },
    }[k]
    fake_row.__bool__.return_value = True

    fake_conn = AsyncMock()
    fake_conn.fetchrow = AsyncMock(return_value=fake_row)

    ref = await load_reference_from_db(fake_conn)
    assert ref is not None
    assert "feature_histograms" in ref
    assert ref["prediction_distribution"] == [0.4, 0.3, 0.3]


@pytest.mark.asyncio
async def test_load_reference_from_db_none() -> None:
    """load_reference_from_db returns None when no champion exists."""
    fake_conn = AsyncMock()
    fake_conn.fetchrow = AsyncMock(return_value=None)

    ref = await load_reference_from_db(fake_conn)
    assert ref is None


@pytest.mark.asyncio
async def test_load_reference_from_db_no_ref_key() -> None:
    """load_reference_from_db returns None when metrics has no reference_distributions."""
    fake_row = MagicMock()
    fake_row.__getitem__.side_effect = lambda k: {"metrics": {"accuracy": 0.85}}[k]
    fake_row.__bool__.return_value = True

    fake_conn = AsyncMock()
    fake_conn.fetchrow = AsyncMock(return_value=fake_row)

    ref = await load_reference_from_db(fake_conn)
    assert ref is None


# ---------------------------------------------------------------------------
# Filesystem fallback
# ---------------------------------------------------------------------------
