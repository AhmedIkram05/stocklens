"""Normalise yfinance news items across the 0.x flat and 1.x nested shapes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _field(article: dict[str, Any]) -> dict[str, Any]:
    content = article.get("content")
    return content if isinstance(content, dict) else article


def normalise_articles(articles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Return at most *limit* articles with stable keys."""
    out: list[dict[str, Any]] = []
    for article in articles[:limit]:
        content = _field(article)
        provider = content.get("provider")
        canonical = content.get("canonicalUrl")
        published = content.get("pubDate")
        if not published and content.get("providerPublishTime"):
            published = datetime.fromtimestamp(
                content["providerPublishTime"], tz=timezone.utc
            ).isoformat()
        out.append(
            {
                "title": content.get("title"),
                "publisher": (
                    provider.get("displayName")
                    if isinstance(provider, dict)
                    else content.get("publisher")
                ),
                "link": (
                    canonical.get("url")
                    if isinstance(canonical, dict)
                    else content.get("link") or canonical
                ),
                "published_date": published,
                "summary": content.get("summary") or content.get("description"),
            }
        )
    return out
