"""
Reference distributions for Evidently drift detection.

Stores the champion model's training feature distributions so the prediction
logger can compare live inference data against the reference and detect
data drift (feature drift, target drift).

Storage: model_registry.metrics JSONB (primary) + filesystem JSON (fallback).
Format: per-feature histograms (20-bin) + raw value samples (up to 1000 per
feature) for KS-test compatibility.

Usage::

    from ml.reference_distributions import (
        build_reference_from_training_data,
        store_reference_in_db,
        load_reference_from_db,
    )

    # After champion promotion:
    ref = build_reference_from_training_data(
        global_sequences=train_features,  # (N, 30, 17) or (N, 17)
        global_labels=train_labels,
        feature_names=FEATURE_NAMES,
    )
    await store_reference_in_db(conn, ref, model_version="v22")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Default path for the filesystem fallback
DEFAULT_REFERENCE_PATH = Path("/model_artifacts/reference_data.json")

# 17 feature names in canonical order — must match prediction_logger.FEATURE_NAMES
FEATURE_NAMES: list[str] = [
    "log_ret_1d",
    "log_ret_5d",
    "log_ret_21d",
    "ma_5",
    "ma_10",
    "ma_20",
    "ma_50",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "vol_30d",
    "vol_rank",
    "vol_pct",
    "excess_ret_1d",
    "excess_ret_5d",
    "excess_ret_21d",
]


def _json_fallback(obj: Any) -> str:
    """JSON serializer fallback for non-serializable types (e.g. numpy)."""
    if isinstance(obj, np.generic):
        return obj.item()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def build_reference_from_training_data(
    global_sequences: np.ndarray,
    global_labels: np.ndarray,
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    """Build a reference distribution dict from training data.

    Produces per-feature histograms (20-bin) + raw value samples for KS test,
    and the prediction class distribution.

    Args:
        global_sequences: Feature matrix of shape ``(N, 30, 17)`` (full windows)
            or ``(N, 17)`` (already flattened). RAW (pre-normalization) values.
        global_labels: Labels array of shape ``(N,)`` with class indices (0/1/2).

    Returns:
        A serializable dict with ``feature_histograms`` (each containing
        ``histogram``, ``bin_edges``, ``values``, ``n``) and
        ``prediction_distribution`` (3-element list of class proportions).
    """
    names = feature_names or FEATURE_NAMES

    # Flatten sequences: (N, 30, 17) -> (N*30, 17) or pass-through if flat
    if global_sequences.ndim == 3:
        flat_features = global_sequences.reshape(-1, global_sequences.shape[-1])
    else:
        flat_features = global_sequences

    # Remove NaN rows
    flat_features = flat_features[~np.isnan(flat_features).any(axis=1)]

    if flat_features.shape[0] == 0:
        logger.warning("no_valid_features_for_reference_distribution")
        return _empty_reference(names)

    n_features = flat_features.shape[1]

    # Per-feature histograms (20-bin) + raw value samples
    feature_histograms: dict[str, dict[str, Any]] = {}
    for i in range(min(n_features, len(names))):
        values = flat_features[:, i]
        values = values[~np.isnan(values)]
        if len(values) == 0:
            feature_histograms[names[i]] = {
                "histogram": [0] * 20,
                "bin_edges": [0.0] * 21,
                "values": [],
                "n": 0,
            }
            continue

        hist, bin_edges = np.histogram(values, bins=20)
        # Sample up to 1000 values for KS test storage
        sample = values
        if len(sample) > 1000:
            rng = np.random.default_rng(42)
            sample = rng.choice(sample, 1000, replace=False)

        feature_histograms[names[i]] = {
            "histogram": hist.tolist(),
            "bin_edges": bin_edges.tolist(),
            "values": sample.tolist(),
            "n": int(len(values)),
        }

    # Prediction class distribution
    if len(global_labels) > 0:
        unique, counts = np.unique(global_labels, return_counts=True)
        pred_dist = [0.0, 0.0, 0.0]
        for cls, count in zip(unique, counts):
            idx = int(cls)
            if 0 <= idx < 3:
                pred_dist[idx] = float(count / len(global_labels))
    else:
        pred_dist = [1 / 3, 1 / 3, 1 / 3]

    reference: dict[str, Any] = {
        "feature_histograms": feature_histograms,
        "prediction_distribution": pred_dist,
        "n_training_samples": int(flat_features.shape[0]),
        "n_features": n_features,
        "feature_names": names[:n_features],
        "computed_at": __import__("datetime").datetime.now().isoformat(),
    }

    logger.info(
        "Reference distribution built",
        extra={
            "n_features": len(feature_histograms),
            "n_samples": flat_features.shape[0],
        },
    )
    return reference


def _empty_reference(feature_names: list[str]) -> dict[str, Any]:
    """Return an empty reference dict for when no valid features exist."""
    return {
        "feature_histograms": {},
        "prediction_distribution": [1 / 3, 1 / 3, 1 / 3],
        "n_training_samples": 0,
        "n_features": 0,
        "feature_names": feature_names,
        "computed_at": __import__("datetime").datetime.now().isoformat(),
    }


async def store_reference_in_db(
    conn: Any,
    reference: dict[str, Any],
    model_version: str,
) -> None:
    """Store reference distributions in model_registry.metrics JSONB.

    Updates the champion row's ``metrics`` column to include a
    ``reference_distributions`` key.

    Args:
        conn: Open asyncpg connection.
        reference: Dict from ``build_reference_from_training_data``.
        model_version: Current model version for identification.
    """
    await conn.execute(
        """
        UPDATE model_registry
        SET metrics = jsonb_set(
            COALESCE(metrics, '{}'::jsonb),
            '{reference_distributions}',
            $1::jsonb
        )
        WHERE alias = 'champion'
        """,
        json.dumps(reference, default=_json_fallback),
    )
    logger.info(
        "Reference distributions stored in DB",
        extra={
            "model_version": model_version,
            "n_features": len(reference.get("feature_histograms", {})),
        },
    )


async def load_reference_from_db(conn: Any) -> dict[str, Any] | None:
    """Load reference distributions from model_registry.metrics JSONB.

    Args:
        conn: Open asyncpg connection.

    Returns:
        The reference distributions dict, or ``None`` if no champion exists
        or no reference distributions have been stored.
    """
    row = await conn.fetchrow("SELECT metrics FROM model_registry WHERE alias = 'champion'")
    if row is None or row["metrics"] is None:
        return None

    metrics = dict(row["metrics"])
    ref = metrics.get("reference_distributions")
    if ref is None:
        logger.info("No reference distributions found in champion metrics")
        return None

    logger.info(
        "Loaded reference distributions from DB",
        extra={"n_features": len(ref.get("feature_histograms", {}))},
    )
    return dict(ref)


# ---------------------------------------------------------------------------
# Filesystem fallback (backward-compatible, kept for non-DB contexts)
# ---------------------------------------------------------------------------


def save_reference(
    reference: dict[str, Any],
    path: str | Path = DEFAULT_REFERENCE_PATH,
) -> str:
    """Save the reference distribution dict as JSON (filesystem fallback).

    Args:
        reference: Dict from ``build_reference_from_training_data``.
        path: Filesystem path to write to.

    Returns:
        The path the reference data was written to.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(reference, f, indent=2, default=_json_fallback)
    logger.info("Reference data saved to %s", path)
    return str(path)


def load_reference(
    path: str | Path = DEFAULT_REFERENCE_PATH,
) -> dict[str, Any] | None:
    """Load a previously saved reference distribution dict.

    Args:
        path: Path to the JSON file.

    Returns:
        The reference dict, or ``None`` if the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        return None
    with open(path) as f:
        reference = json.load(f)
    logger.info("Loaded reference data from %s", path)
    return reference
