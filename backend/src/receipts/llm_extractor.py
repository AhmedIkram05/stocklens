"""
Bedrock Claude Haiku structured extraction for receipt OCR.

Built as an async service that:
1. Builds a structured JSON extraction prompt.
2. Calls ``ChatBedrock`` (same pattern as ``src/receipts/bedrock.py``).
3. Parses the JSON response into a validated ``LLMExtractionResult``.
4. Checks the Redis cache before making Bedrock calls.
5. Retries transient failures with exponential backoff.
6. Degrades gracefully — returns ``None`` on permanent failure.

Retry policy
------------
- Transient failures (timeout, 5xx): retry ``LLM_MAX_RETRIES`` times with
  exponential backoff starting at ``LLM_RETRY_BACKOFF`` seconds.
- Permanent failures (4xx, unparseable JSON): return ``None`` immediately.

Vision path
-----------
``extract_with_vision()`` sends the receipt *image* directly to Bedrock via
the Converse API so the model sees the layout and fonts — much better than
the legacy path which sends garbled Tesseract text.
"""

from __future__ import annotations

import json
import re

import structlog
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.receipts.cache import get_cached_llm, set_cached_llm

logger = structlog.get_logger()


# ── Response model ────────────────────────────────────────────────────────


class LLMExtractionResult(BaseModel):
    """Structured output from Bedrock Haiku extraction."""

    merchant_name: str | None = None
    total_amount: float | None = None
    date: str | None = None  # ISO format string
    line_items: list[dict] = Field(default_factory=list)
    category: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)


# ── Prompt template ───────────────────────────────────────────────────────


_EXTRACTION_PROMPT_TEMPLATE = (
    "Extract receipt data from this OCR text. Return JSON with these fields:\n"
    "- merchant_name: string or null\n"
    "- total_amount: number or null\n"
    "- date: ISO date string (YYYY-MM-DD) or null\n"
    "- line_items: array of {{description: string, quantity: number, amount: number}}\n"
    "- category: one of Groceries, Dining, Transport, Utilities, Entertainment, "
    "Healthcare, Shopping, Travel, Education, Uncategorised\n"
    "- confidence: object with keys merchant_name, total_amount, date, "
    "line_items, category (each 0.0-1.0)\n\n"
    "Only return valid JSON, no other text.\n\n"
    "OCR text:\n{raw_text}"
)


def _build_extraction_prompt(raw_text: str) -> str:
    """Build a prompt for structured JSON extraction via Bedrock."""
    return _EXTRACTION_PROMPT_TEMPLATE.format(raw_text=raw_text)


# ── Vision prompt template ────────────────────────────────────────────────

_VISION_EXTRACTION_PROMPT: str = (
    "Extract receipt information from this image. "
    "Return ONLY valid JSON, no other text or markdown:\n"
    '{"merchant_name": "str or null", '
    '"total_amount": 0.0 or null, '
    '"date": "YYYY-MM-DD or null", '
    '"line_items": [{"description": "str", "quantity": 1, "amount": 0.0}], '
    '"category": "Groceries|Dining|Transport|Utilities|Entertainment|Healthcare|Shopping|Travel|Education|Uncategorised", '  # noqa: E501
    '"confidence": {"merchant_name": 0.0-1.0, "total_amount": 0.0-1.0, "date": 0.0-1.0, "line_items": 0.0-1.0}}'  # noqa: E501
)


def _image_format_from_bytes(image_bytes: bytes) -> str:
    """Detect image format from magic bytes for Bedrock Converse API."""
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    # ponytail: HEIC/HEIF not supported by Nova — convert in caller if needed
    return "jpeg"


async def extract_with_vision(image_bytes: bytes) -> LLMExtractionResult | None:
    """Extract receipt data by sending the image directly to a vision model.

    Uses the Bedrock Converse API (``boto3.client('bedrock-runtime').converse``)
    with a multimodal prompt — the model sees the receipt layout, not a garbled
    OCR transcript.  Falls back to ``None`` on any failure so the caller can
    degrade to the Tesseract-based pipeline.
    """
    # ponytail: no retry decorator — just try once and fall through on failure
    import boto3

    try:
        client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
        img_format = _image_format_from_bytes(image_bytes)

        response = client.converse(
            modelId=settings.BEDROCK_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": _VISION_EXTRACTION_PROMPT},
                        {"image": {"format": img_format, "source": {"bytes": image_bytes}}},
                    ],
                }
            ],
            inferenceConfig={
                "temperature": 0,
                "maxTokens": settings.LLM_MAX_TOKENS,
            },
        )
    except Exception:
        logger.warning("vision_api_failed", exc_info=True)
        return None

    # ── Parse response ────────────────────────────────────────────────
    try:
        content_blocks = response["output"]["message"]["content"]
        response_text = next(b["text"] for b in content_blocks if "text" in b)
    except (KeyError, StopIteration):
        logger.warning("vision_response_no_text", response=str(response)[:200])
        return None

    # Strip markdown code fences that models sometimes wrap JSON in
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            logger.warning("vision_response_not_object", type=type(parsed).__name__)
            return None
        return LLMExtractionResult(**parsed)
    except (json.JSONDecodeError, Exception):
        logger.warning("vision_response_unparseable", response=response_text[:200])
        return None


# ── Transient-failure predicate ───────────────────────────────────────────


def _is_transient_failure(exc: BaseException) -> bool:
    """Return ``True`` if the exception is likely transient.

    Timeouts and 5xx errors from the Bedrock API should be retried.
    4xx errors (bad request, auth) should not.
    """
    msg = str(exc).lower()
    if "timeout" in msg or "read timed out" in msg:
        return True
    if "5" in msg and (
        "server error" in msg or "internal" in msg or "gateway" in msg or "503" in msg
    ):
        return True
    return False


# ── Main extraction function ──────────────────────────────────────────────


def _should_retry(exc: BaseException) -> bool:
    """Tenacity predicate: only retry on transient failures."""
    return _is_transient_failure(exc)


async def extract_with_llm(
    raw_text: str,
    override_prompt: str | None = None,
) -> LLMExtractionResult | None:
    """Extract structured receipt data using Bedrock Claude Haiku.

    Steps
    -----
    1. Check Redis cache — if a previous LLM result exists for this OCR
       text, return it (avoids duplicate Bedrock calls).
    2. Build a structured JSON extraction prompt.
    3. Call ``ChatBedrock`` with temperature=0.
    4. Parse the JSON response into ``LLMExtractionResult``.
    5. Cache the result in Redis on success.
    6. Retry transient failures with exponential backoff.
    7. Return ``None`` on permanent failure (graceful degradation).

    Parameters
    ----------
    raw_text:
        OCR-extracted text from a receipt image.
    override_prompt:
        Optional — override the default prompt. Useful for tests.

    Returns
    -------
    LLMExtractionResult | None
        Structured extraction, or ``None`` if extraction failed.
    """
    # ── 1. Check cache ───────────────────────────────────────────────────
    cached = await get_cached_llm(raw_text)
    if cached is not None:
        logger.info("llm_cache_hit", text_hash=raw_text[:32])
        try:
            return LLMExtractionResult(**cached)
        except Exception:
            logger.warning("llm_cache_stale", exc_info=True)
            # Stale cache entry — fall through and re-extract.

    # ── 2. Build prompt ──────────────────────────────────────────────────
    prompt = override_prompt or _build_extraction_prompt(raw_text)

    # ── 3. Call Bedrock (with retry) ─────────────────────────────────────
    try:
        result_json = await _call_bedrock_with_retry(prompt)
    except Exception:
        logger.exception("llm_extraction_failed_all_retries")
        return None

    if result_json is None:
        return None

    # ── 4. Parse response ────────────────────────────────────────────────
    try:
        # Strip markdown code fences that Bedrock sometimes wraps JSON in
        cleaned = re.sub(
            r"^```(?:json)?\s*\n?",
            "",
            result_json.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\n?\s*```$", "", cleaned).strip()
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            logger.warning("llm_response_not_object", type=type(parsed).__name__)
            return None
        result = LLMExtractionResult(**parsed)
    except (json.JSONDecodeError, Exception):
        logger.warning("llm_response_unparseable", response=result_json[:200])
        return None

    # ── 5. Cache on success (skip if all fields null — not useful) ──────
    all_null = all(
        getattr(result, f, None) is None for f in ("merchant_name", "total_amount", "date")
    )
    if not all_null:
        try:
            await set_cached_llm(raw_text, result.model_dump())
        except Exception:
            logger.warning("llm_cache_write_failed", exc_info=True)

    logger.info(
        "llm_extraction_successful",
        merchant=result.merchant_name,
        total=result.total_amount,
        item_count=len(result.line_items),
    )

    return result


@retry(
    stop=stop_after_attempt(settings.LLM_MAX_RETRIES + 1),
    wait=wait_exponential(multiplier=1.0, min=1, max=10),
    retry=retry_if_exception(_should_retry),
    reraise=True,
)
async def _call_bedrock_with_retry(prompt: str) -> str | None:
    """Call Bedrock Claude Haiku and return the raw response text.

    Retries on transient failures (timeout, 5xx) up to 3 times with
    exponential backoff (1s, 2s, 4s).
    """
    from langchain_aws import ChatBedrock  # noqa: PLC0415

    from src.config import settings  # noqa: PLC0415

    llm = ChatBedrock(
        model_id=settings.BEDROCK_MODEL_ID,
        region_name=settings.AWS_REGION,
        model_kwargs={
            "temperature": 0,
            "max_tokens": settings.LLM_MAX_TOKENS,
        },
    )

    response = await llm.ainvoke(prompt)
    content = response.content
    if content is None:
        return None
    return str(content).strip()
