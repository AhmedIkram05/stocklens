"""
Redis-backed caching layer for the NLP cascade OCR system.

Provides two categories of cache keys reusing the existing
``ConnectionPool`` from ``src.cache.redis``:

1. **LLM response cache** — avoids duplicate Bedrock calls for identical OCR
   text (keyed by ``sha256(raw_text)[:16]``, 24 h TTL).
2. **Background enrichment status** — allows the frontend to poll whether a
   pending LLM enrichment is still running (keyed by receipt ID, 1 h TTL).

Settings are imported inside each function to avoid circular imports
(config → receipts → cache → config).
"""

from __future__ import annotations

import hashlib
import json

from src.cache.redis import get_redis  # shared pool, initialised in lifespan


def _text_hash(raw_text: str) -> str:
    """Return the first 16 hex characters of the SHA-256 hash of *raw_text*."""
    return hashlib.sha256(raw_text.encode()).hexdigest()[:16]


async def get_cached_llm(raw_text: str) -> dict | None:
    """Check the LLM response cache by text hash. Returns parsed dict or ``None``.

    Cache key: ``llm_cache:{sha256(raw_text)[:16]}``
    """

    key = f"llm_cache:{_text_hash(raw_text)}"
    cached = await (await get_redis()).get(key)
    return json.loads(cached) if cached else None


async def set_cached_llm(raw_text: str, result: dict) -> None:
    """Store an LLM extraction result in the cache.

    Cache key: ``llm_cache:{sha256(raw_text)[:16]}``
    TTL: ``settings.LLM_CACHE_TTL`` (24 hours by default).
    """
    from src.config import settings  # noqa: PLC0415

    key = f"llm_cache:{_text_hash(raw_text)}"
    await (await get_redis()).set(key, json.dumps(result), ex=settings.LLM_CACHE_TTL)


async def set_enrich_status(receipt_id: str, status: str) -> None:
    """Set the enrichment status for a receipt.

    Key: ``enrich_status:{receipt_id}``
    TTL: ``settings.ENRICH_STATUS_TTL`` (1 hour by default).
    """
    from src.config import settings  # noqa: PLC0415

    await (await get_redis()).set(
        f"enrich_status:{receipt_id}", status, ex=settings.ENRICH_STATUS_TTL
    )


async def get_enrich_status(receipt_id: str) -> str | None:
    """Return the current enrichment status for a receipt, or ``None``."""
    return await (await get_redis()).get(f"enrich_status:{receipt_id}")
