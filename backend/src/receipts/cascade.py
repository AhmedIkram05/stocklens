"""
Confidence-gated cascade orchestrator for the receipt OCR pipeline.

Flow
----
1. Run ``process_receipt()`` (existing regex parsing) via ``asyncio.to_thread()``.
2. Score each extracted field with a heuristic confidence.
3. Compute ``overall_confidence`` as the average of merchant, total, and date.
4. If the regex result is trustworthy (``overall`` above threshold, OCR read
   quality acceptable, and the merchant confirmed against known merchants)
   → return it immediately (source = ``"regex"``).
5. Otherwise escalate to ``extract_with_llm()`` (correction backstop).
6. If LLM fails → return regex result (source = ``"degraded"``).
7. Detect discrepancies between regex and LLM.
8. Merge per-field by picking the higher-confidence value.
9. Return a ``CascadeResult``.

Design notes
------------
- ``known_merchants`` is loaded once from ``SEED_CATEGORIES`` at module load
  and used by fuzzy matching to boost merchant confidence.
- ``process_receipt()`` is CPU-bound (Tesseract) — must be run in a thread
  pool via ``asyncio.to_thread()``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from decimal import Decimal
from typing import Any

import structlog

from src.categories.seed import SEED_CATEGORIES
from src.config import settings
from src.receipts.llm_extractor import LLMExtractionResult, extract_with_llm, extract_with_vision
from src.receipts.merchant_match import fuzzy_match_merchant
from src.receipts.models import (
    CascadeResult,
    ExtractedItem,
    FieldConfidence,
    ReceiptExtraction,
)
from src.receipts.ocr import process_receipt

logger = structlog.get_logger()

# ── Known merchants loaded once at module load ───────────────────────────

KNOWN_MERCHANTS: list[str] = [kw for cat in SEED_CATEGORIES for kw in cat["merchant_keywords"]]

# ponytail: merchant at/above this conf was fuzzy-verified vs known merchants;
# below it, the regex found a name but couldn't confirm it → worth an LLM check.
MERCHANT_VERIFIED_CONFIDENCE = 0.95
RECONCILIATION_TOLERANCE = Decimal("0.05")


# ── Arithmetic reconciliation ─────────────────────────────────────────────


def _sum_item_amounts(items: list[dict] | None) -> Decimal | None:
    """Sum line-item amounts when every item has a numeric amount."""
    if not items:
        return None
    total = Decimal("0")
    for item in items:
        amount = item.get("amount")
        if amount is None:
            return None
        total += Decimal(str(amount))
    return total


def _apply_reconciliation(
    result: dict[str, Any],
    field_confs: dict[str, FieldConfidence],
) -> tuple[dict[str, FieldConfidence], bool]:
    """Cross-check total vs line items and adjust field confidence.

    Returns updated confidences and whether a reconciliation mismatch was found.
    When items sum to the extracted total (± tolerance), both fields get a
    confidence boost. A mismatch lowers total confidence so the cascade can
    escalate to vision/LLM correction.
    """
    items = result.get("line_items") or []
    total = result.get("total_amount")
    items_sum = _sum_item_amounts(items)

    if total is None or items_sum is None or not items:
        return field_confs, False

    # Single-item receipts are often service lines priced only at the total row.
    if len(items) < 2:
        return field_confs, False

    total_dec = Decimal(str(total))
    delta = abs(items_sum - total_dec)
    reconciled = delta <= RECONCILIATION_TOLERANCE

    total_fc = field_confs.get("total")
    items_fc = field_confs.get("items")

    if reconciled:
        if total_fc is not None and total_fc.value is not None:
            field_confs["total"] = total_fc.model_copy(
                update={"confidence": min(0.96, total_fc.confidence + 0.06)}
            )
        if items_fc is not None and items_fc.value is not None:
            field_confs["items"] = items_fc.model_copy(
                update={"confidence": min(0.95, items_fc.confidence + 0.10)}
            )
        logger.debug(
            "reconciliation_passed",
            items_sum=float(items_sum),
            total=float(total_dec),
        )
        return field_confs, False

    if total_fc is not None and total_fc.value is not None:
        field_confs["total"] = total_fc.model_copy(
            update={"confidence": max(0.55, total_fc.confidence - 0.20)}
        )
    logger.info(
        "reconciliation_mismatch",
        items_sum=float(items_sum),
        total=float(total_dec),
        delta=float(delta),
    )
    return field_confs, True


# ── Heuristic confidence scoring ─────────────────────────────────────────


def _score_heuristic_confidence(
    result: dict[str, Any],
    raw_text: str,
    known_merchants: list[str] | None = None,
) -> dict[str, FieldConfidence]:
    """Score each field from the regex extraction with a heuristic confidence.

    Confidence guidelines
    ---------------------
    - ``total``: 0.88 if found (a labelled regex match is useful but can
      still be an OCR digit error), 0.0 if missing.
    - ``merchant``: 0.90 if found, boosted to 0.95 if fuzzy-matched against
      known merchants, 0.0 if missing.
    - ``date``: 0.85 if found, 0.0 if missing.
    - ``items``: 0.50 + (N * 0.10), capped at 0.90. 0.0 if no items.

    Parameters
    ----------
    result:
        Raw dict from ``process_receipt()``.
    raw_text:
        The OCR-extracted text (used for hash identification only — not used
        for scoring directly).
    known_merchants:
        Optional list of known merchant keywords for fuzzy matching. Defaults
        to the module-level ``KNOWN_MERCHANTS``.

    Returns
    -------
    dict[str, FieldConfidence]
        Per-field confidence scores keyed by field name.
    """
    merchants = known_merchants if known_merchants is not None else KNOWN_MERCHANTS
    confidences: dict[str, FieldConfidence] = {}

    # ── Total ────────────────────────────────────────────────────────────
    total = result.get("total_amount")
    if total is not None:
        confidences["total"] = FieldConfidence(
            value=float(total),
            confidence=0.88,
            source="regex",
        )
    else:
        confidences["total"] = FieldConfidence(
            value=None,
            confidence=0.0,
            source="regex",
        )

    # ── Merchant ─────────────────────────────────────────────────────────
    merchant = result.get("merchant_name")
    if merchant is not None:
        base_conf = 0.90
        # Fuzzy-match against known merchants for confidence boost
        if merchants:
            match_name, match_score = fuzzy_match_merchant(str(merchant), merchants)
            if match_name and match_score >= 80:
                base_conf = 0.95
                logger.debug(
                    "merchant_fuzzy_match",
                    merchant=str(merchant),
                    matched=match_name,
                    score=match_score,
                )
        confidences["merchant"] = FieldConfidence(
            value=str(merchant),
            confidence=base_conf,
            source="regex",
        )
    else:
        confidences["merchant"] = FieldConfidence(
            value=None,
            confidence=0.0,
            source="regex",
        )

    # ── Date ─────────────────────────────────────────────────────────────
    parsed_date = result.get("date")
    if parsed_date is not None:
        confidences["date"] = FieldConfidence(
            value=str(parsed_date),
            confidence=0.85,
            source="regex",
        )
    else:
        confidences["date"] = FieldConfidence(
            value=None,
            confidence=0.0,
            source="regex",
        )

    # ── Items ────────────────────────────────────────────────────────────
    items = result.get("line_items", [])
    if items:
        item_count = len(items)
        conf = min(0.90, 0.50 + item_count * 0.10)
        confidences["items"] = FieldConfidence(
            value=items,
            confidence=conf,
            source="regex",
        )
    else:
        confidences["items"] = FieldConfidence(
            value=None,
            confidence=0.0,
            source="regex",
        )

    return confidences


# ── Overall confidence ────────────────────────────────────────────────────


def _compute_overall_confidence(field_confidences: dict[str, FieldConfidence]) -> float:
    """Compute overall confidence as the average of merchant, total, and date.

    Items are excluded from the overall because they are optional on many
    receipts (e.g. a receipt for a single item or a subscription).
    """
    scores = []
    for key in ("merchant", "total", "date"):
        fc = field_confidences.get(key)
        if fc is not None:
            scores.append(fc.confidence)
    return round(sum(scores) / len(scores), 4) if scores else 0.0


# ── Escalation decision ──────────────────────────────────────────────────


def _should_escalate(
    overall: float,
    field_confs: dict[str, FieldConfidence],
    ocr_confidence: float | None,
    reconciliation_mismatch: bool = False,
) -> tuple[bool, str]:
    """Decide whether to escalate the regex result to the LLM correction layer.

    The fast regex path is kept only when the read is trustworthy AND every
    core field is confirmed.  Escalate when ANY of:

    * ``overall`` confidence is below ``CASCADE_CONFIDENCE_THRESHOLD``
      (a core field is missing or low).
    * the OCR engine's own confidence (``ocr_confidence``) is below
      ``CASCADE_OCR_CONFIDENCE_FLOOR`` — the image read itself is poor, so a
      misread is likely even if all fields were "found".
    * the merchant was extracted but NOT fuzzy-verified against known
      merchants (confidence ``< MERCHANT_VERIFIED_CONFIDENCE``) — let the LLM
      confirm/correct the name.
    * line-item amounts do not reconcile with the extracted total.

    Returns ``(escalate, reasons)`` where ``reasons`` is a comma-joined string
    for logging.
    """
    reasons: list[str] = []

    if overall < settings.CASCADE_CONFIDENCE_THRESHOLD:
        reasons.append("low_overall")

    if ocr_confidence is not None and ocr_confidence < settings.CASCADE_OCR_CONFIDENCE_FLOOR:
        reasons.append("low_ocr_quality")

    merchant = field_confs.get("merchant")
    if (
        merchant is not None
        and merchant.value is not None
        and merchant.confidence < MERCHANT_VERIFIED_CONFIDENCE
    ):
        reasons.append("unverified_merchant")

    if reconciliation_mismatch:
        reasons.append("reconciliation_mismatch")

    return (len(reasons) > 0, ",".join(reasons))


# ── Discrepancy detection ────────────────────────────────────────────────


def _values_differ(regex_value: object, llm_value: object) -> bool:
    """Return ``True`` if the two values are meaningfully different.

    Handles ``None``, string normalisation, and floating-point comparison.
    """
    if regex_value is None and llm_value is None:
        return False
    if regex_value is None or llm_value is None:
        return True

    # Normalise both to strings for comparison
    r_str = str(regex_value).strip().lower()
    l_str = str(llm_value).strip().lower()

    # Skip comparison if either is empty
    if not r_str or not l_str:
        return False

    return r_str != l_str


def _detect_discrepancies(
    heuristic: dict[str, FieldConfidence],
    llm: LLMExtractionResult,
) -> list[dict]:
    """Compare heuristic and LLM results, logging differences.

    Only logs a discrepancy when **both** sources have confidence >= 0.5 for
    the field AND the values meaningfully differ. This prevents noise from
    low-confidence fields where disagreement is expected, not anomalous.
    """
    discrepancies: list[dict] = []

    # Map heuristic keys → (heuristic FieldConfidence, LLM value, LLM confidence key)
    # LLM uses different field names (merchant_name / total_amount) than
    # heuristic (merchant / total) so we must map both.
    field_map = {
        "merchant": (heuristic.get("merchant"), llm.merchant_name, "merchant_name"),
        "total": (heuristic.get("total"), llm.total_amount, "total_amount"),
        "date": (heuristic.get("date"), llm.date, "date"),
    }

    for field_name, (h_fc, llm_val, llm_key) in field_map.items():
        if h_fc is None:
            continue
        h_conf = h_fc.confidence
        # Get LLM's own confidence for this field (default 0.0 if absent)
        l_conf = llm.confidence.get(llm_key, 0.0)

        if h_conf >= 0.5 and l_conf >= 0.5:
            if _values_differ(h_fc.value, llm_val):
                discrepancies.append(
                    {
                        "field": field_name,
                        "regex": str(h_fc.value) if h_fc.value is not None else None,
                        "llm": str(llm_val) if llm_val is not None else None,
                    }
                )

    return discrepancies


# ── Merge results ─────────────────────────────────────────────────────────


def _should_prefer_llm(
    heuristic: FieldConfidence | None,
    llm_value: object,
    llm_confidence: float,
) -> bool:
    """Choose a model correction only when it is credible and auditable.

    A regex match is not ground truth: OCR can preserve a ``TOTAL`` label
    while reading one digit incorrectly.  Let a confident vision/text model
    correct a disagreeing, non-verified heuristic value, while keeping a
    known-merchant match (0.95) as the conservative tie-breaker.
    """
    if llm_value is None or llm_confidence < 0.75:
        return False
    if heuristic is None or heuristic.value is None:
        return True
    if not _values_differ(heuristic.value, llm_value):
        return llm_confidence > heuristic.confidence
    return heuristic.confidence < MERCHANT_VERIFIED_CONFIDENCE


def _merge_results(
    heuristic: dict[str, FieldConfidence],
    llm: LLMExtractionResult,
    discrepancies: list[dict],
) -> CascadeResult:
    """Pick the higher-confidence value for each field.

    For fields where LLM provided a higher confidence (or heuristic has very
    low confidence), the LLM value is preferred.  Otherwise the heuristic
    (regex) value is kept.
    """
    # Build the base extraction from heuristic
    merchant = heuristic.get("merchant")
    total = heuristic.get("total")
    h_date = heuristic.get("date")
    items = heuristic.get("items")

    # Prefer high-confidence LLM corrections for disputed OCR values.  Every
    # disagreement remains in ``discrepancies`` for monitoring and review.
    if llm.merchant_name is not None:
        llm_merchant_conf = llm.confidence.get("merchant_name", 0.0)
        if _should_prefer_llm(merchant, llm.merchant_name, llm_merchant_conf):
            merchant = FieldConfidence(
                value=llm.merchant_name,
                confidence=llm_merchant_conf,
                source="llm",
            )

    if llm.total_amount is not None:
        llm_total_conf = llm.confidence.get("total_amount", 0.0)
        if _should_prefer_llm(total, llm.total_amount, llm_total_conf):
            total = FieldConfidence(
                value=llm.total_amount,
                confidence=llm_total_conf,
                source="llm",
            )

    if llm.date is not None:
        llm_date_conf = llm.confidence.get("date", 0.0)
        if _should_prefer_llm(h_date, llm.date, llm_date_conf):
            h_date = FieldConfidence(
                value=llm.date,
                confidence=llm_date_conf,
                source="llm",
            )

    if llm.line_items:
        llm_items_conf = llm.confidence.get("line_items", 0.0)
        if _should_prefer_llm(items, llm.line_items, llm_items_conf):
            items = FieldConfidence(
                value=llm.line_items,
                confidence=llm_items_conf,
                source="llm",
            )

    # Build merged field_confidences
    field_confidences: dict[str, FieldConfidence] = {}
    if merchant is not None:
        field_confidences["merchant"] = merchant
    if total is not None:
        field_confidences["total"] = total
    if h_date is not None:
        field_confidences["date"] = h_date
    if items is not None:
        field_confidences["items"] = items

    overall = _compute_overall_confidence(field_confidences)

    extraction = ReceiptExtraction(
        merchant_name=_get_str(merchant),
        total=Decimal(str(total.value)) if total and total.value is not None else None,
        date=_parse_date_str(h_date.value if h_date else None),
        items=_items_field_to_model(items),
    )

    return CascadeResult(
        extraction=extraction,
        field_confidences=field_confidences,
        overall_confidence=overall,
        source="cascade",
        discrepancies=discrepancies,
        raw_text="",
        llm_category=llm.category,
    )


def _get_str(fc: FieldConfidence | None) -> str | None:
    """Extract a string value from a FieldConfidence."""
    if fc is None or fc.value is None:
        return None
    return str(fc.value)


def _raw_items_to_model(items: list[dict]) -> list[ExtractedItem]:
    """Convert raw dict items (from regex or LLM) to ``list[ExtractedItem]``.

    Both sources produce items as ``list[dict]`` with keys
    ``description``, ``quantity``, ``amount``. This maps them to
    ``ExtractedItem(name=…, quantity=…, price=…)``.
    """
    result: list[ExtractedItem] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("description") or ""
        quantity = item.get("quantity", 1)
        price = item.get("amount")
        # ponytail: naive int conversion — fromisoformat decimal later if needed
        try:
            qty = int(quantity) if quantity is not None else 1
        except (ValueError, TypeError):
            qty = 1
        try:
            price_f = float(price) if price is not None else 0.0
        except (ValueError, TypeError):
            price_f = 0.0
        result.append(ExtractedItem(name=str(name), quantity=qty, price=price_f))
    return result


def _items_field_to_model(
    items: FieldConfidence | None,
) -> list[ExtractedItem]:
    """Convert the items FieldConfidence (contains list[dict]) to list[ExtractedItem]."""
    if items is None or items.value is None:
        return []
    raw = items.value
    if not isinstance(raw, list):
        return []
    return _raw_items_to_model(raw)


def _parse_date_str(val: object) -> date | None:
    """Parse a ``date``, ISO string, or ``None`` into a ``date`` or ``None``."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val)
        except ValueError:
            return None
    return None


# ── Cascade entry point ──────────────────────────────────────────────────


async def cascade_extract(
    image_bytes: bytes,
    known_merchants: list[str] | None = None,
) -> CascadeResult:
    """Full cascade: OCR → regex → confidence check → optional LLM escalation.

    Parameters
    ----------
    image_bytes:
        Raw image bytes (JPEG, PNG, or HEIC).
    known_merchants:
        Optional list of known merchant keywords. Defaults to the module-level
        list loaded from ``SEED_CATEGORIES``.

    Returns
    -------
    CascadeResult
        The extraction result with per-field confidence, discrepancies, and
        the cascade source label.
    """
    start_time = time.perf_counter()

    # ── 1. Run CPU-bound OCR in thread pool ────────────────────────────
    try:
        result = await asyncio.to_thread(process_receipt, image_bytes)
    except ValueError:
        logger.warning("cascade_corrupt_image", exc_info=True)
        return CascadeResult(
            extraction=ReceiptExtraction(),
            field_confidences={},
            overall_confidence=0.0,
            source="failed",
            discrepancies=[],
            raw_text="",
        )

    raw_text = result.get("ocr_raw_text", "")

    if not raw_text.strip():
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            "cascade_ocr_empty",
            processing_time_ms=round(elapsed_ms, 2),
        )
        return CascadeResult(
            extraction=ReceiptExtraction(),
            field_confidences={},
            overall_confidence=0.0,
            source="failed",
            discrepancies=[],
            raw_text="",
        )

    # ── 2. Score heuristic confidence ──────────────────────────────────
    merchants = known_merchants if known_merchants is not None else KNOWN_MERCHANTS
    field_confs = _score_heuristic_confidence(result, raw_text, merchants)
    field_confs, reconciliation_mismatch = _apply_reconciliation(result, field_confs)
    overall = _compute_overall_confidence(field_confs)

    # ── 3. Build base extraction ───────────────────────────────────────
    total = result.get("total_amount")
    raw_items: list[dict] = result.get("line_items", [])
    extraction = ReceiptExtraction(
        merchant_name=result.get("merchant_name"),
        total=Decimal(str(total)) if total is not None else None,
        date=result.get("date"),
        items=_raw_items_to_model(raw_items),
    )

    # ── 4. Decide whether the fast regex path is good enough ──────────
    # Escalate to the LLM when overall is low, the OCR read quality is poor,
    # or the merchant was extracted but not confirmed against known merchants.
    should_escalate, reasons = _should_escalate(
        overall, field_confs, result.get("ocr_confidence"), reconciliation_mismatch
    )
    if not should_escalate:
        logger.info(
            "cascade_regex_only",
            overall_confidence=overall,
            threshold=settings.CASCADE_CONFIDENCE_THRESHOLD,
        )
        return CascadeResult(
            extraction=extraction,
            field_confidences=field_confs,
            overall_confidence=overall,
            source="regex",
            discrepancies=[],
            raw_text=raw_text,
        )

    # ── 5. Escalate to LLM (vision first, text fallback) ──────────────
    logger.info(
        "cascade_escalating_to_llm",
        overall_confidence=overall,
        threshold=settings.CASCADE_CONFIDENCE_THRESHOLD,
        reasons=reasons,
    )

    llm_result = await extract_with_vision(image_bytes)

    if llm_result is None:
        logger.info("cascade_vision_failed_falling_back_to_text")
        llm_result = await extract_with_llm(raw_text)

    if llm_result is None:
        logger.warning("cascade_llm_failed_falling_back")
        return CascadeResult(
            extraction=extraction,
            field_confidences=field_confs,
            overall_confidence=overall,
            source="degraded",
            discrepancies=[],
            raw_text=raw_text,
        )

    # ── 7. Detect discrepancies ────────────────────────────────────────
    discrepancies = _detect_discrepancies(field_confs, llm_result)

    # ── 8. Merge results ───────────────────────────────────────────────
    merged = _merge_results(field_confs, llm_result, discrepancies)
    merged.raw_text = raw_text

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "cascade_complete",
        source=merged.source,
        overall_confidence=merged.overall_confidence,
        discrepancies=len(merged.discrepancies),
        processing_time_ms=round(elapsed_ms, 2),
    )

    return merged
