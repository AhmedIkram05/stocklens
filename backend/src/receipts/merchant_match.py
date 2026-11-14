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
from rapidfuzz import fuzz, process

from src.categories.seed import SEED_CATEGORIES

logger = structlog.get_logger()

# ── Known merchants loaded once at module load ───────────────────────────

KNOWN_MERCHANTS: list[str] = [kw for cat in SEED_CATEGORIES for kw in cat["merchant_keywords"]]
# Lower-cased once at import: the default path is called many times per receipt
# (parse_merchant scans candidate lines), and re-lowering 209 strings each call
# was pure waste.
KNOWN_MERCHANTS_LOWER: list[str] = [m.lower() for m in KNOWN_MERCHANTS]


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

    if known_merchants is None:
        merchants = KNOWN_MERCHANTS
        lowered = KNOWN_MERCHANTS_LOWER
    else:
        merchants = known_merchants
        lowered = [known.lower() for known in merchants]
    if not merchants:
        return None, 0.0

    # One native scan; extractOne resolves ties to the first choice, matching
    # the previous strict `>` loop. processor=None keeps the explicit lower()
    # (rapidfuzz's default processor also strips punctuation, changing scores).
    result = process.extractOne(
        merchant_name.lower(),
        lowered,
        scorer=fuzz.token_set_ratio,
        processor=None,
        score_cutoff=80,
    )
    if result is None:
        return None, 0.0

    _, best_score, best_idx = result
    best_match = merchants[best_idx]
    logger.debug(
        "merchant_fuzzy_match",
        input=merchant_name,
        match=best_match,
        score=round(best_score, 1),
    )
    return best_match, best_score
