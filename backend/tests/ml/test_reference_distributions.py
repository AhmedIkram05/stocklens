"""
Tests for reference distribution building, DB storage, and filesystem fallback.

Tests that need DB mocking use AsyncMock for asyncpg.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from ml.reference_distributions import (
    FEATURE_NAMES,
    _json_fallback,
    build_reference_from_training_data,
    load_reference,
    load_reference_from_db,
    save_reference,
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


def test_save_reference_roundtrip() -> None:
    """save_reference + load_reference roundtrip preserves data."""
    ref = {
        "feature_histograms": {
            "log_ret_1d": {
                "histogram": list(range(20)),
                "bin_edges": list(range(21)),
                "values": [0.5] * 50,
                "n": 50,
            },
        },
        "prediction_distribution": [1 / 3, 1 / 3, 1 / 3],
        "n_training_samples": 50,
        "n_features": 1,
        "feature_names": ["log_ret_1d"],
        "computed_at": "2026-01-01T00:00:00",
    }

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tmp = f.name

    try:
        path = save_reference(ref, path=tmp)
        assert path == tmp

        loaded = load_reference(path=tmp)
        assert loaded is not None
        assert loaded["n_training_samples"] == 50
        assert loaded["feature_histograms"]["log_ret_1d"]["n"] == 50
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_load_reference_nonexistent() -> None:
    """load_reference returns None when file does not exist."""
    result = load_reference(path="/tmp/nonexistent_ref_test.json")
    assert result is None


def test_save_reference_creates_parent_dir() -> None:
    """save_reference creates parent directories automatically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nested = Path(tmpdir) / "sub" / "nested" / "ref.json"
        path = save_reference(
            {"feature_histograms": {}, "prediction_distribution": [1, 0, 0]},
            path=str(nested),
        )
        assert Path(path).exists()
        Path(path).unlink()


def test_json_fallback_numpy_types() -> None:
    """_json_fallback converts numpy types to native Python."""
    assert _json_fallback(np.float32(3.14)) == pytest.approx(3.14, abs=1e-6)
    assert _json_fallback(np.int64(99)) == 99
    assert _json_fallback(np.float64(2.71)) == pytest.approx(2.71)

    with pytest.raises(TypeError):
        _json_fallback(object())


def test_feature_names_are_correct() -> None:
    """FEATURE_NAMES matches expected 17 canonical names."""
    assert len(FEATURE_NAMES) == 17
    assert FEATURE_NAMES[0] == "log_ret_1d"
    assert FEATURE_NAMES[-1] == "excess_ret_21d"
    assert "vol_pct" in FEATURE_NAMES
