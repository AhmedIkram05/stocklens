"""
Merchant-to-category mapping logic.

Uses a two-stage approach:
1. **Keyword matching** — checks the merchant name (lowercased) against each
   category's ``merchant_keywords`` list.
2. **Bedrock LLM fallback** — if keyword matching fails, invokes Claude Haiku
   through Bedrock to classify the merchant.

The category lists are loaded on first use via :func:`load_categories`.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import structlog
from pydantic import BaseModel

from src.categories.seed import SEED_CATEGORIES
from src.config import settings

logger = structlog.get_logger()


# ── In-memory category cache ──────────────────────────────────────────────────


class CategoryRule(BaseModel):
    """A single category with its keywords and tickers."""

    id: str
    name: str
    description: str | None = None
    merchant_keywords: list[str] = []
    associated_tickers: list[str] = []


_category_cache: list[CategoryRule] | None = None


def load_categories(db_categories: list[dict[str, Any]] | None = None) -> list[CategoryRule]:
    """Load categories from DB or fall back to seed data.

    Call this on startup with the result of a ``SELECT * FROM spending_categories``
    query. If *db_categories* is ``None`` or empty the built-in seed list is used.
    """
    global _category_cache

    if db_categories:
        _category_cache = [
            CategoryRule(
                id=str(c["id"]),
                name=c["name"],
                description=c.get("description"),
                merchant_keywords=c.get("merchant_keywords") or [],
                associated_tickers=c.get("associated_tickers") or [],
            )
            for c in db_categories
        ]
    else:
        # Fall back to seed data — assign a placeholder ID since there is no DB row
        _category_cache = [
            CategoryRule(
                id=f"seed_{i}",
                name=c["name"],
                description=c["description"],
                merchant_keywords=c["merchant_keywords"],
                associated_tickers=c["associated_tickers"],
            )
            for i, c in enumerate(SEED_CATEGORIES)
        ]

    return _category_cache


def get_categories() -> list[CategoryRule]:
    """Return the loaded category cache, loading seed data if necessary."""
    global _category_cache
    if _category_cache is None:
        load_categories()
    return _category_cache or []


# ── Keyword matching ──────────────────────────────────────────────────────────


def _normalise(text: str) -> str:
    """Lower-case and strip punctuation."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def match_by_keyword(merchant_name: str) -> Optional[CategoryRule]:
    """Return the first category whose keywords match the merchant name.

    Matching is case-insensitive and checks if any keyword appears as a
    substring of the normalised merchant name.
    """
    normalised = _normalise(merchant_name)
    if not normalised:
        return None

    for category in get_categories():
        for keyword in category.merchant_keywords:
            # Use word-boundary-at-start so "tfl" doesn't match inside "netflix"
            # but "mcdonald" still matches inside "mcdonalds"
            if re.search(rf"(?<!\w){re.escape(keyword.lower())}", normalised):
                logger.debug(
                    "category_keyword_match",
                    merchant=merchant_name,
                    category=category.name,
                    keyword=keyword,
                )
                return category

    return None


# ── Bedrock LLM fallback ──────────────────────────────────────────────────────


_bedrock_client: Any = None


def _get_bedrock_client():
    """Lazily initialise the Bedrock runtime client (AWS boto3)."""
    global _bedrock_client
    if _bedrock_client is None:
        import boto3

        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.AWS_REGION,
        )
    return _bedrock_client


def _sanitise_merchant(merchant_name: str) -> str:
    """Strip control characters and limit length to prevent prompt injection."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", merchant_name)
    return cleaned[:256]


def _build_bedrock_prompt(merchant_name: str, categories: list[CategoryRule]) -> str:
    """Build a prompt for Claude Haiku to classify a merchant."""
    category_names = "\n".join(f"- {c.name}: {c.description}" for c in categories)

    return (
        "You are a merchant classification assistant. "
        "Given a merchant name, classify it into exactly "
        f"one of the following categories:\n\n{category_names}\n\n"
        "Respond with ONLY the category name, nothing else."
        f"\n\nMerchant: {merchant_name}\nCategory:"
    )


async def classify_with_bedrock(merchant_name: str) -> Optional[CategoryRule]:
    """Use Claude Haiku via Bedrock to classify the merchant into a category.

    This is a fallback when keyword matching fails. Returns ``None`` if
    Bedrock is unavailable or the response does not match a known category.
    """
    categories = get_categories()
    if not categories:
        return None

    merchant_name = _sanitise_merchant(merchant_name)
    prompt = _build_bedrock_prompt(merchant_name, categories)

    try:
        client = _get_bedrock_client()

        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": prompt}],
            }
        )

        response = await asyncio.to_thread(
            client.invoke_model,
            modelId=settings.BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        result = response["body"].read().decode("utf-8")
        data = json.loads(result)
        category_name = data.get("content", [{}])[0].get("text", "").strip()

        # Match the returned name against known categories
        for cat in categories:
            if cat.name.lower() == category_name.lower():
                logger.info(
                    "category_bedrock_match",
                    merchant=merchant_name,
                    category=cat.name,
                )
                return cat

        logger.warning(
            "category_bedrock_unrecognised",
            merchant=merchant_name,
            response=category_name,
        )
        return None

    except Exception:
        logger.exception(
            "category_bedrock_error",
            merchant=merchant_name,
        )
        return None


# ── Combined resolution ───────────────────────────────────────────────────────


async def resolve_category(merchant_name: str) -> Optional[CategoryRule]:
    """Resolve a merchant name to a category.

    Stage 1: Keyword matching (fast, no external dependencies).
    Stage 2: Bedrock LLM classification (slow, requires AWS credentials).
    Returns ``None`` if neither method produces a match.
    """
    if not merchant_name:
        return None

    # Stage 1 — keyword match
    category = match_by_keyword(merchant_name)
    if category is not None:
        return category

    # Stage 2 — Bedrock fallback
    category = await classify_with_bedrock(merchant_name)
    return category
