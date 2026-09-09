"""Statistical gate for champion/challenger promotion.

Promotion requires BOTH:
  1. Effect size: challenger DA beats champion DA by > ``min_pp`` (default 2pp).
  2. Significance: one-sided binomial p-value < ``alpha`` (default 0.05),
     testing H0 "challenger true directional rate <= champion DA".

Why one-sample instead of paired bootstrap: at gate time only aggregated
champion DA is available (``model_registry.metrics``), not the champion's
per-sample predictions — a paired test is impossible without them. Treating
champion DA as a fixed baseline needs only the challenger's directional
counts (``n`` decisions, ``k`` correct), which ``evaluate()`` already sees.

# ponytail: paired bootstrap/McNemar when champion per-sample preds are
# stored (add correct_champ vector to model_registry, then compare diffs).
# Until then this is the correct minimal test — no scipy dependency.
"""

from __future__ import annotations

import math

MIN_PP = 0.02
ALPHA = 0.05


def binomial_one_sided_p(k: int, n: int, p0: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p0), normal approx with continuity correction.

    Exact ``math.comb`` summation is O(n) — fine for small n but wasteful at
    test-set scale, so the normal approximation is used throughout. Stdlib
    only (``math.erfc``), no scipy.
    """
    if n <= 0:
        return 1.0
    if p0 <= 0.0:
        return 0.0 if k > 0 else 1.0
    if p0 >= 1.0:
        return 1.0
    var = n * p0 * (1.0 - p0)
    if var <= 0.0:
        return 1.0
    z = (k - 0.5 - n * p0) / math.sqrt(var)
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def should_promote(
    champion_da: float | None,
    challenger_da: float,
    n_directional: int | None = None,
    n_correct: int | None = None,
    min_pp: float = MIN_PP,
    alpha: float = ALPHA,
) -> dict:
    """Decide promotion. Pure function — no DB/MLflow, trivially testable."""
    if champion_da is None:
        return {
            "promote": True,
            "champion_da": None,
            "challenger_da": challenger_da,
            "improvement_pp": None,
            "p_value": None,
            "reason": "no-champion",
        }
    improvement = challenger_da - champion_da
    if improvement <= min_pp:
        return {
            "promote": False,
            "champion_da": champion_da,
            "challenger_da": challenger_da,
            "improvement_pp": improvement,
            "p_value": None,
            "reason": "below-threshold",
        }
    if n_directional is None or n_correct is None:
        # ponytail: legacy fallback for rows recorded before evaluate()
        # stored directional counts. Drop once backfilled.
        return {
            "promote": True,
            "champion_da": champion_da,
            "challenger_da": challenger_da,
            "improvement_pp": improvement,
            "p_value": None,
            "reason": "above-threshold-legacy-no-counts",
        }
    if n_directional <= 0:
        return {
            "promote": False,
            "champion_da": champion_da,
            "challenger_da": challenger_da,
            "improvement_pp": improvement,
            "p_value": None,
            "reason": "no-directional-samples",
        }
    p = binomial_one_sided_p(int(n_correct), int(n_directional), float(champion_da))
    return {
        "promote": bool(p < alpha),
        "champion_da": champion_da,
        "challenger_da": challenger_da,
        "improvement_pp": improvement,
        "p_value": p,
        "reason": "significant" if p < alpha else "not-significant",
    }
