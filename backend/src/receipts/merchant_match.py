"""
Fuzzy merchant name matching via RapidFuzz.

Loads known merchants from ``SEED_CATEGORIES`` (from
``src/categories/seed.py``) at module load and provides a single public
function: ``fuzzy_match_merchant()``.

Used by the cascade confidence scorer to boost merchant confidence when the
extracted merchant name closely matches a known entity.
"""

from __future__ import annotations

import structlog
from rapidfuzz import fuzz

from src.categories.seed import SEED_CATEGORIES

logger = structlog.get_logger()

# ── Known merchants loaded once at module load ───────────────────────────

KNOWN_MERCHANTS: list[str] = [kw for cat in SEED_CATEGORIES for kw in cat["merchant_keywords"]]


# ── Public API ────────────────────────────────────────────────────────────


def fuzzy_match_merchant(
    merchant_name: str,
    known_merchants: list[str] | None = None,
) -> tuple[str | None, float]:
    """Match *merchant_name* against the list of known merchants.

    Uses ``rapidfuzz.fuzz.token_set_ratio`` for matching — this normalises
    word order so "Tesco Stores Ltd" still matches "TESCO STORES".

    Parameters
    ----------
    merchant_name:
        The merchant name extracted from the receipt.
    known_merchants:
        Optional override list. Defaults to the module-level
        ``KNOWN_MERCHANTS`` loaded from ``SEED_CATEGORIES`` at import time.

    Returns
    -------
    tuple[str | None, float]
        ``(best_match_name, score)`` where *score* is 0.0–100.0.
        Returns ``(None, 0.0)`` when no match exceeds the threshold (80).
    """
    if not merchant_name or not merchant_name.strip():
        return None, 0.0

    merchants = known_merchants if known_merchants is not None else KNOWN_MERCHANTS
    if not merchants:
        return None, 0.0

    best_score = 0.0
    best_match: str | None = None

    for known in merchants:
        score = fuzz.token_set_ratio(merchant_name.lower(), known.lower())
        if score > best_score:
            best_score = score
            best_match = known

    if best_score >= 80:
        logger.debug(
            "merchant_fuzzy_match",
            input=merchant_name,
            match=best_match,
            score=round(best_score, 1),
        )
        return best_match, best_score

    return None, 0.0
