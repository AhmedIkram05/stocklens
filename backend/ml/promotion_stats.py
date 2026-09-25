"""Statistical gates for champion/challenger promotion.

Two gates:

1. ``decide_promotion_paired`` (primary): the champion is re-scored on the
   challenger's test set (with the champion's own normalisation), and an
   exact two-sided McNemar test is run on the discordant directional
   decisions of the two models over the SAME windows. Effect size still
   requires the challenger to beat the champion by > ``min_pp`` on that test
   set. This replaces the old unpaired gate, which compared directional
   accuracies measured on different evaluation periods as if they were
   commensurable.

2. ``should_promote`` (fallback): one-sided binomial test treating the
   champion's stored DA as a fixed baseline. Only used when no champion
   checkpoint exists yet (first promotion) or paired re-scoring fails.
"""

from __future__ import annotations

import math

import numpy as np

MIN_PP = 0.02
ALPHA = 0.05


def mcnemar_exact(b: int, c: int) -> dict:
    """Two-sided exact McNemar test on discordant pairs. Stdlib only.

    With b = count(model A wrong, model B right) and c = count(A right,
    B wrong), under H0 (equal accuracy) b ~ Binomial(b+c, 0.5). The exact
    two-sided p-value is 2 * P(X <= min(b, c)) for X ~ Binomial(n, 0.5),
    clipped to [0, 1].

    Returns:
        {"statistic_b": b, "statistic_c": c, "p_value": p}.
    """
    n = b + c
    if n == 0:
        return {"statistic_b": b, "statistic_c": c, "p_value": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return {"statistic_b": b, "statistic_c": c, "p_value": min(1.0, 2.0 * tail)}


def decide_promotion_paired(
    correct_champion: np.ndarray,
    correct_challenger: np.ndarray,
    min_pp: float = MIN_PP,
    alpha: float = ALPHA,
) -> dict:
    """Paired promotion decision from per-window correctness vectors.

    Args:
        correct_champion: (N,) bool — champion correct on each directional window.
        correct_challenger: (N,) bool — challenger correct on the same windows.
        min_pp: Minimum DA improvement (fraction, e.g. 0.02 = 2pp).
        alpha: McNemar significance level.

    Returns:
        Decision dict with promote/champion_da/challenger_da/improvement_pp/
        p_value/statistic_b/statistic_c/reason.
    """
    champion_correct = np.asarray(correct_champion, dtype=bool)
    challenger_correct = np.asarray(correct_challenger, dtype=bool)
    n = len(champion_correct)
    if len(challenger_correct) != n:
        return {
            "promote": False,
            "champion_da": None,
            "challenger_da": None,
            "improvement_pp": None,
            "p_value": None,
            "reason": "no-paired-data",
        }
    if n == 0:
        # No directional windows to compare — never auto-promote on no evidence.
        return {
            "promote": False,
            "champion_da": None,
            "challenger_da": None,
            "improvement_pp": None,
            "p_value": None,
            "reason": "no-directional-windows",
        }

    champion_da = float(champion_correct.mean())
    challenger_da = float(challenger_correct.mean())
    improvement = challenger_da - champion_da

    b = int((~champion_correct & challenger_correct).sum())
    c = int((champion_correct & ~challenger_correct).sum())
    mcnemar = mcnemar_exact(b, c)

    if improvement <= min_pp:
        return {
            "promote": False,
            "champion_da": champion_da,
            "challenger_da": challenger_da,
            "improvement_pp": improvement,
            "p_value": mcnemar["p_value"],
            "statistic_b": b,
            "statistic_c": c,
            "reason": "below-threshold",
        }
    return {
        "promote": bool(mcnemar["p_value"] < alpha),
        "champion_da": champion_da,
        "challenger_da": challenger_da,
        "improvement_pp": improvement,
        "p_value": mcnemar["p_value"],
        "statistic_b": b,
        "statistic_c": c,
        "reason": "significant" if mcnemar["p_value"] < alpha else "not-significant",
    }


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
    """Unpaired fallback gate. Pure function — no DB/MLflow, trivially testable.

    Only for the first promotion (no champion yet) or when paired re-scoring
    is impossible; a paired McNemar gate (``decide_promotion_paired``) is
    preferred whenever the champion checkpoint is available.
    """
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
        # Legacy fallback for rows recorded before evaluate() stored
        # directional counts. Drop once backfilled.
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
