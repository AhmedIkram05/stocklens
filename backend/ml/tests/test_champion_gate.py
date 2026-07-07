"""
Tests for the champion comparison gate and reference distributions.

All tests are pure Python with no DB or MLflow dependency.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from ml.reference_distributions import (
    _json_fallback,
    build_reference_from_training_data,
    load_reference,
    save_reference,
)

# ---------------------------------------------------------------------------
# Reference distributions
# ---------------------------------------------------------------------------


def test_build_reference_basic() -> None:
    """Happy path: 50 samples, 17 features, 3 classes."""
    rng = np.random.default_rng(42)
    features = rng.normal(loc=0.0, scale=1.0, size=(50, 17)).astype(np.float32)
    labels = np.array([0] * 20 + [1] * 15 + [2] * 15)  # DOWN=0, FLAT=1, UP=2

    ref = build_reference_from_training_data(features, labels)

    assert ref["n_training_samples"] == 50
    assert ref["n_features"] == 17
    assert len(ref["feature_names"]) == 17
    assert len(ref["feature_histograms"]) == 17
    assert len(ref["prediction_distribution"]) == 3  # 3-class proportions
    # Verify histogram structure per feature
    h = ref["feature_histograms"][ref["feature_names"][0]]
    assert len(h["histogram"]) == 20
    assert len(h["bin_edges"]) == 21
    assert len(h["values"]) > 0
    assert h["n"] == 50


def test_build_reference_all_nan_column() -> None:
    """All-NaN column handled gracefully (no crash, valid data for others).

    Row-level NaN removal strips rows where ANY column is NaN.  After
    removal, each remaining column is fully non-NaN.  A column that was
    entirely NaN would have zero surviving rows, returning the empty ref.
    """
    features = np.zeros((50, 3), dtype=np.float32)
    features[:, 0] = 3.0  # col a: all valid
    features[:, 2] = 5.0  # col c: all valid
    features[10:, 1] = np.nan  # col b: rows 10+ NaN, rows 0-9 valid (10 valid)
    labels = np.array([2] * 50)

    ref = build_reference_from_training_data(features, labels, ["a", "b", "c"])

    # After row removal, only rows 0-9 survive (all 3 cols valid in those rows)
    assert ref["n_training_samples"] == 10
    assert ref["feature_histograms"]["b"]["n"] == 10  # 10 surviving rows × col b


def test_build_reference_all_nan_column_all_rows_removed() -> None:
    """When every column is NaN in every row, empty reference is returned."""
    features = np.full((50, 3), np.nan, dtype=np.float32)
    labels = np.array([2] * 50)

    ref = build_reference_from_training_data(features, labels, ["a", "b", "c"])
    assert ref["n_training_samples"] == 0


def test_build_reference_single_sample() -> None:
    """Single sample does not crash."""
    features = np.array([[1.0, 2.0]], dtype=np.float32)
    labels = np.array([2])
    ref = build_reference_from_training_data(features, labels, ["a", "b"])
    assert ref["n_training_samples"] == 1
    for name in ["a", "b"]:
        assert ref["feature_histograms"][name]["n"] == 1


def test_save_load_roundtrip() -> None:
    """Written JSON can be loaded back losslessly."""
    ref = {
        "feature_histograms": {
            "a": {
                "histogram": [10] * 20,
                "bin_edges": list(range(21)),
                "values": [0.5] * 50,
                "n": 50,
            },
            "b": {
                "histogram": [5] * 20,
                "bin_edges": list(range(21)),
                "values": [1.0] * 50,
                "n": 50,
            },
        },
        "prediction_distribution": [0.4, 0.3, 0.3],
        "n_training_samples": 50,
        "n_features": 2,
        "feature_names": ["a", "b"],
        "computed_at": "2026-01-01T00:00:00",
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        save_reference(ref, path=tmp)
        loaded = load_reference(path=tmp)
        assert loaded is not None
        assert loaded["n_training_samples"] == 50
        assert loaded["feature_histograms"]["a"]["n"] == 50
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_load_nonexistent_file() -> None:
    """load_reference returns None when the file does not exist."""
    result = load_reference(path="/tmp/nonexistent_reference_data_xyz.json")
    assert result is None


def test_json_fallback_numpy() -> None:
    """_json_fallback converts numpy scalars to native Python types."""
    assert _json_fallback(np.float32(1.5)) == 1.5
    assert _json_fallback(np.int64(42)) == 42

    with pytest.raises(TypeError):
        _json_fallback(ValueError("not supported"))


# ---------------------------------------------------------------------------
# Champion metrics — mock asyncpg DB
# ---------------------------------------------------------------------------


def _mock_mlflow_module() -> MagicMock:
    """Patch sys.modules so mlflow imports don't fail outside Docker."""
    import sys

    mock = MagicMock()
    mock.set_tracking_uri = MagicMock()
    mock.set_experiment = MagicMock()
    mock.tracking.MlflowClient = MagicMock()
    mock.active_run.return_value = None
    mock.start_run.return_value.__enter__.return_value = MagicMock()
    mock.end_run = MagicMock()
    mock.MlflowClient.return_value = MagicMock()
    mock.pytorch = MagicMock()
    mock.pytorch.autolog = MagicMock()
    mock.pytorch.pytorch = MagicMock()
    sys.modules["mlflow"] = mock
    sys.modules["mlflow.tracking"] = mock.tracking
    sys.modules["mlflow.pytorch"] = mock.pytorch
    return mock


@pytest.mark.asyncio
async def test_read_champion_metrics_found() -> None:
    """Returns champion metrics when DB has a champion row."""
    _mock_mlflow_module()
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    fake_row = MagicMock()
    fake_row.__getitem__.side_effect = lambda k: {
        "metrics": {"directional_accuracy": 0.52, "accuracy": 0.45},
    }[k]
    fake_row.__bool__.return_value = True

    fake_conn = AsyncMock()
    fake_conn.fetchrow = AsyncMock(return_value=fake_row)
    fake_conn.close = AsyncMock()

    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        metrics = await mgr.read_champion_metrics()

    assert metrics is not None
    assert metrics["directional_accuracy"] == 0.52


@pytest.mark.asyncio
async def test_read_champion_metrics_none() -> None:
    """Returns None when no champion row exists."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    fake_conn = AsyncMock()
    fake_conn.fetchrow = AsyncMock(return_value=None)
    fake_conn.close = AsyncMock()

    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        metrics = await mgr.read_champion_metrics()

    assert metrics is None


# ---------------------------------------------------------------------------
# Champion comparison gate — pure logic
# ---------------------------------------------------------------------------


def _promote_decision(champion_da: float | None, challenger_da: float) -> dict:
    """Replicates the promotion logic from pipeline.py."""
    da_improvement = challenger_da - champion_da if champion_da is not None else None
    promote = champion_da is None or (da_improvement is not None and da_improvement > 0.02)
    return {
        "promote": promote,
        "champion_da": champion_da,
        "challenger_da": challenger_da,
        "improvement_pp": da_improvement,
    }


def test_promote_when_no_champion() -> None:
    """First trained model is always promoted (no champion to compare)."""
    result = _promote_decision(champion_da=None, challenger_da=0.50)
    assert result["promote"] is True


def test_promote_when_beats_by_more_than_2pp() -> None:
    """Promotes when challenger > champion + 2pp."""
    result = _promote_decision(champion_da=0.50, challenger_da=0.55)
    assert result["promote"] is True
    assert result["improvement_pp"] == pytest.approx(0.05)


def test_no_promote_when_challenger_worse() -> None:
    """Challenger worse than champion — no promotion."""
    result = _promote_decision(champion_da=0.50, challenger_da=0.48)
    assert result["promote"] is False


def test_no_promote_when_below_threshold() -> None:
    """Improvement below 2pp does not promote."""
    result = _promote_decision(champion_da=0.50, challenger_da=0.519)
    assert result["promote"] is False
    assert result["improvement_pp"] == pytest.approx(0.019)
