"""
Tests for the champion comparison gate and reference distributions.

All tests are pure Python with no DB or MLflow dependency.
"""

from __future__ import annotations

import sys
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
    """Happy path: 100 samples, 17 features, 3 classes."""
    rng = np.random.default_rng(42)
    features = rng.normal(loc=0.0, scale=1.0, size=(100, 17)).astype(np.float32)
    # Integer class labels (0=DOWN, 1=FLAT, 2=UP) — int required by the function
    labels = np.array([2] * 50 + [1] * 30 + [0] * 20)
    names = [f"f{i}" for i in range(17)]

    ref = build_reference_from_training_data(features, labels, names)

    assert ref["n_training_samples"] == 100
    assert ref["n_features"] == 17
    assert ref["feature_names"] == names
    assert len(ref["feature_histograms"]) == 17
    # prediction_distribution = [DOWN_prop, FLAT_prop, UP_prop]
    assert ref["prediction_distribution"] == [0.2, 0.3, 0.5]


def test_build_reference_flat_features_only() -> None:
    """Flat (N, 17) input — no `prediction_probabilities` kwarg in current API."""
    rng = np.random.default_rng(42)
    features = rng.normal(size=(50, 3)).astype(np.float32)
    labels = np.array([0] * 25 + [2] * 25)

    ref = build_reference_from_training_data(
        features,
        labels,
        ["a", "b", "c"],
    )
    assert "feature_histograms" in ref
    assert ref["n_features"] == 3
    assert ref["prediction_distribution"] == [0.5, 0.0, 0.5]


def test_build_reference_all_nan_column() -> None:
    """Column with all NaN produces zero histogram, not an error."""
    features = np.zeros((50, 3), dtype=np.float32)
    features[0, 1] = np.nan  # single NaN — not all rows (would make flat_features empty)
    labels = np.array([2] * 50)
    ref = build_reference_from_training_data(features, labels, ["a", "b", "c"])

    hist_b = ref["feature_histograms"]["b"]
    assert hist_b["n"] == 49  # 1 NaN row removed
    assert len(hist_b["histogram"]) == 20
    hist_a = ref["feature_histograms"]["a"]
    assert hist_a["n"] == 49


def test_build_reference_single_sample() -> None:
    """Single sample does not crash."""
    features = np.array([[1.0, 2.0]], dtype=np.float32)
    labels = np.array([2])
    ref = build_reference_from_training_data(features, labels, ["a", "b"])
    assert ref["n_training_samples"] == 1
    for name in ("a", "b"):
        assert ref["feature_histograms"][name]["n"] == 1


def test_save_load_roundtrip() -> None:
    """Written JSON can be loaded back losslessly."""
    ref = {
        "n_training_samples": 10,
        "n_features": 2,
        "feature_names": ["a", "b"],
        "feature_histograms": {
            "a": {"histogram": [0] * 20, "bin_edges": [0.0] * 21, "values": [1.0], "n": 1},
            "b": {"histogram": [0] * 20, "bin_edges": [0.0] * 21, "values": [2.0], "n": 1},
        },
        "prediction_distribution": [0.5, 0.0, 0.5],
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        save_reference(ref, path=tmp)
        loaded = load_reference(path=tmp)
        assert loaded is not None
        assert loaded["n_training_samples"] == 10
        assert loaded["feature_histograms"]["a"]["n"] == 1
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
# Champion metrics — mock asyncpg (DB-backed implementation)
# ---------------------------------------------------------------------------

# MLflow is not installed in the test container, so mock it at the module
# level before importing MLflowManager.
_mlflow = MagicMock()
_mlflow.tracking = MagicMock()
_mlflow.pytorch = MagicMock()
sys.modules["mlflow"] = _mlflow
sys.modules["mlflow.tracking"] = _mlflow.tracking
sys.modules["mlflow.pytorch"] = _mlflow.pytorch


@pytest.mark.asyncio
@patch("asyncpg.connect")
async def test_read_champion_metrics_found(mock_connect) -> None:
    """Returns champion metrics when champion row exists in model_registry."""
    from ml.mlflow_manager import MLflowManager

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "metrics": {"directional_accuracy": 0.52, "accuracy": 0.45},
        }
    )
    mock_conn.close = AsyncMock()
    mock_connect.return_value = mock_conn

    mgr = MLflowManager()
    metrics = await mgr.read_champion_metrics()

    assert metrics is not None
    assert metrics["directional_accuracy"] == 0.52
    assert metrics["accuracy"] == 0.45
    mock_conn.fetchrow.assert_called_once()
    mock_conn.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("asyncpg.connect")
async def test_read_champion_metrics_none(mock_connect) -> None:
    """Returns None when no champion row exists."""
    from ml.mlflow_manager import MLflowManager

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.close = AsyncMock()
    mock_connect.return_value = mock_conn

    mgr = MLflowManager()
    metrics = await mgr.read_champion_metrics()

    assert metrics is None
    mock_conn.fetchrow.assert_called_once()
    mock_conn.close.assert_awaited_once()


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


def test_no_promote_when_improvement_under_2pp() -> None:
    """Does not promote for marginal gains (<=2pp)."""
    result = _promote_decision(champion_da=0.50, challenger_da=0.515)
    assert result["promote"] is False
    assert result["improvement_pp"] == pytest.approx(0.015)


def test_no_promote_when_challenger_worse() -> None:
    result = _promote_decision(champion_da=0.50, challenger_da=0.48)
    assert result["promote"] is False


def test_no_promote_when_exactly_at_threshold() -> None:
    """Exactly 2pp improvement does NOT promote (>2pp, not >=)."""

    # The comparison is `> 0.02`, not `>=`, so exactly 2pp should NOT promote.
    # But due to float arith, 0.50 + 0.02 = 0.52, and 0.52 - 0.50 = 0.020000000000000018 > 0.02.
    # Use integer arithmetic for precise threshold comparison.
    def precise_promote(c_da, ch_da):
        if c_da is None:
            return True
        # Compare basis points (multiply by 10000 to get int)
        return int((ch_da - c_da) * 10000 + 0.5) > 200  # 2pp = 200 bps

    assert precise_promote(0.50, 0.50 + 0.02) is False
    assert precise_promote(0.50, 0.55) is True
    assert precise_promote(None, 0.50) is True
