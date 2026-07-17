"""Drift detection service — PSI, KS, JS-divergence computation."""

from __future__ import annotations

import math

import numpy as np
import structlog
from scipy.stats import ks_2samp

from src.config import settings

logger = structlog.get_logger()

# ── Alert thresholds ──────────────────────────────────────────────────────────
# Ponytail: single global thresholds from config. Tune per-feature if
# signal-to-noise varies widely across features.
PSI_ALERT_THRESHOLD: float = settings.DRIFT_ALERT_PSI_THRESHOLD
KS_ALERT_THRESHOLD: float = settings.DRIFT_ALERT_KS_THRESHOLD
JS_ALERT_THRESHOLD: float = settings.DRIFT_ALERT_JS_THRESHOLD


# ── Public metrics API ────────────────────────────────────────────────────────
def _eps() -> float:
    """Return a small epsilon to avoid log(0) / division-by-zero."""
    return np.finfo(np.float64).eps


def compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index between two 1-D arrays.

    PSI = Σ (p_i - q_i) * ln(p_i / q_i)
    where p_i = proportion in reference bin, q_i = proportion in current bin.
    """
    # ponytail: single-bin fallback, not a production quantile-optimised split.
    if len(reference) < 2 or len(current) < 2:
        return 0.0

    all_values = np.concatenate([reference, current])
    lo, hi = float(np.nanmin(all_values)), float(np.nanmax(all_values))
    if math.isclose(lo, hi):
        return 0.0

    # Bin edges from percentiles of the reference distribution
    edges = np.percentile(
        reference[~np.isnan(reference)],
        np.linspace(0, 100, bins + 1),
    )
    # Guard: collapse trailing duplicate edges created by many identical values
    edges = np.unique(edges)
    if len(edges) < 2:
        return 0.0

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)

    ref_pct = ref_counts / max(ref_counts.sum(), 1)
    cur_pct = cur_counts / max(cur_counts.sum(), 1)

    # Ensure no zero proportions for log stability
    ref_pct = np.clip(ref_pct, _eps(), None)
    cur_pct = np.clip(cur_pct, _eps(), None)

    psi = np.sum((ref_pct - cur_pct) * np.log(ref_pct / cur_pct))
    return float(psi)


def compute_ks_statistic(reference: np.ndarray, current: np.ndarray) -> dict:
    """Two-sample Kolmogorov-Smirnov test.

    Returns dict with keys ``statistic`` and ``p_value``.
    """
    if len(reference) < 2 or len(current) < 2:
        return {"statistic": 0.0, "p_value": 1.0}

    clean_ref = reference[~np.isnan(reference)]
    clean_cur = current[~np.isnan(current)]
    if len(clean_ref) < 2 or len(clean_cur) < 2:
        return {"statistic": 0.0, "p_value": 1.0}

    res = ks_2samp(clean_ref, clean_cur, method="auto")
    return {"statistic": float(res.statistic), "p_value": float(res.pvalue)}


def compute_js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence between two discrete probability distributions.

    JS(P ‖ Q) = 0.5 * KL(P ‖ M) + 0.5 * KL(Q ‖ M),  M = (P + Q) / 2

    Returns a value in [0, 1] (log base 2 normalised).
    """
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    if p.size == 0 or q.size == 0:
        return 0.0

    p = np.clip(p / max(p.sum(), 1), _eps(), None)
    q = np.clip(q / max(q.sum(), 1), _eps(), None)

    m = 0.5 * (p + q)
    kl_pm = float(np.sum(p * np.log2(p / m)))
    kl_qm = float(np.sum(q * np.log2(q / m)))
    return 0.5 * (kl_pm + kl_qm)


def compute_prediction_distribution(
    predictions: list[str],
    classes: tuple[str, ...] = ("UP", "DOWN", "FLAT"),
) -> np.ndarray:
    """Return the normalised histogram of predictions as an array.

    Entries that don't match any class (e.g. ``"UNKNOWN"``) are silently ignored.
    """
    if not predictions:
        return np.array([1 / len(classes)] * len(classes), dtype=np.float64)
    counts = {c: 0 for c in classes}
    for p in predictions:
        if p in counts:
            counts[p] += 1
    total = max(sum(counts.values()), 1)
    return np.array([counts[c] / total for c in classes], dtype=np.float64)


# ── Feature name mappings ─────────────────────────────────────────────────────
# The order the model receives; used to index into raw feature_stats arrays.
FEATURE_NAMES: tuple[str, ...] = (
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
)


# ── DriftDetector ─────────────────────────────────────────────────────────────


class DriftDetector:
    """Orchestrates per-ticker, per-feature drift detection."""

    def __init__(
        self,
        psi_threshold: float = PSI_ALERT_THRESHOLD,
        ks_threshold: float = KS_ALERT_THRESHOLD,
        js_threshold: float = JS_ALERT_THRESHOLD,
    ) -> None:
        self.psi_threshold = psi_threshold
        self.ks_threshold = ks_threshold
        self.js_threshold = js_threshold

    async def compute_drift(
        self,
        tickers: list[str],
        reference_dist: dict,
        prediction_logs: dict[str, list[dict]],
        model_version: str,
        drift_run_id: str,
        current_period: str,
    ) -> dict:
        """Run all drift metrics across every ticker and feature.

        Returns a dict with ``metrics``, ``alerts_triggered``, ``max_psi``,
        ``max_js_divergence``, and ``overall_verdict`` keys.
        """
        reference_dist = reference_dist or {}
        feature_histograms = reference_dist.get("feature_histograms", {})
        prediction_proportions = reference_dist.get("prediction_proportions")

        # Build reference distributions
        ref_feature_arrays: dict[str, np.ndarray] = {
            k: np.array(v.get("values", []), dtype=np.float64)
            for k, v in feature_histograms.items()
        }

        ref_prediction_dist: np.ndarray | None = None
        if prediction_proportions is not None:
            total = sum(prediction_proportions.values())
            if total > 0:
                ref_prediction_dist = np.array(
                    [prediction_proportions.get(c, 0) / total for c in ("UP", "DOWN", "FLAT")],
                    dtype=np.float64,
                )

        metrics: list[dict] = []
        n_alerts = 0
        max_psi = 0.0
        max_js = 0.0

        for ticker in tickers:
            logs = prediction_logs.get(ticker, [])

            # --- feature-level drift ---
            for feature_name, ref_array in ref_feature_arrays.items():
                cur_values = []
                for entry in logs:
                    stats = (entry.get("features") or {}).get("stats")
                    if stats and "means" in stats:
                        idx = FEATURE_NAMES.index(feature_name)
                        cur_values.append(float(stats["means"][idx]))
                cur_array = np.array(cur_values, dtype=np.float64)

                psi = compute_psi(ref_array, cur_array) if len(cur_array) >= 2 else 0.0
                ks = compute_ks_statistic(ref_array, cur_array)
                # JS via histogram binning (same percentile edges as PSI)
                if len(ref_array) >= 2 and len(cur_array) >= 2:
                    all_vals = np.concatenate([ref_array, cur_array])
                    lo, hi = float(np.nanmin(all_vals)), float(np.nanmax(all_vals))
                    if not math.isclose(lo, hi):
                        edges = np.percentile(
                            ref_array[~np.isnan(ref_array)],
                            np.linspace(0, 100, 11),
                        )
                        edges = np.unique(edges)
                        if len(edges) >= 2:
                            ref_h, _ = np.histogram(ref_array, bins=edges)
                            cur_h, _ = np.histogram(cur_array, bins=edges)
                            js = compute_js_divergence(ref_h, cur_h)
                        else:
                            js = 0.0
                    else:
                        js = 0.0
                else:
                    js = 0.0

                max_psi = max(max_psi, psi)
                max_js = max(max_js, js)

                for mtype, score in [
                    ("psi", psi),
                    ("ks_statistic", ks["statistic"]),
                    ("js_divergence", js),
                ]:
                    alert = False
                    if mtype == "psi" and score >= self.psi_threshold:
                        alert = True
                    elif mtype == "ks_statistic" and score >= self.ks_threshold:
                        alert = True
                    elif mtype == "js_divergence" and score >= self.js_threshold:
                        alert = True

                    if alert:
                        n_alerts += 1

                    metrics.append(
                        {
                            "ticker": ticker,
                            "model_version": model_version,
                            "metric_type": mtype,
                            "feature_name": feature_name,
                            "drift_score": score,
                            "alert_triggered": alert,
                            "reference_period": "training",
                            "current_period": current_period,
                            "details": None,
                        }
                    )

            # --- prediction-distribution drift ---
            if ref_prediction_dist is not None:
                cur_pred_dists = [
                    compute_prediction_distribution(
                        [e.get("prediction", "FLAT") for e in logs],
                    ),
                ]
                if cur_pred_dists:
                    cur_pred_dist = cur_pred_dists[0]
                else:
                    cur_pred_dist = np.array([1 / 3, 1 / 3, 1 / 3])

                js_pred = compute_js_divergence(ref_prediction_dist, cur_pred_dist)
                max_js = max(max_js, js_pred)

                metrics.append(
                    {
                        "ticker": ticker,
                        "model_version": model_version,
                        "metric_type": "prediction_js",
                        "feature_name": "prediction_distribution",
                        "drift_score": js_pred,
                        "alert_triggered": js_pred >= self.js_threshold,
                        "reference_period": "training",
                        "current_period": current_period,
                        "details": None,
                    }
                )
                if js_pred >= self.js_threshold:
                    n_alerts += 1

        return {
            "metrics": metrics,
            "alerts_triggered": n_alerts,
            "max_psi": max_psi,
            "max_js_divergence": max_js,
            "overall_verdict": "drifted" if n_alerts > 0 else "stable",
        }
