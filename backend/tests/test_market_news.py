"""yfinance news normalisation across flat and nested shapes."""

from src.market.news import normalise_articles


def test_flat_shape():
    items = [{"title": "A", "publisher": "P", "link": "https://x", "providerPublishTime": 0}]
    out = normalise_articles(items, 5)
    assert out[0]["title"] == "A"
    assert out[0]["publisher"] == "P"
    assert out[0]["link"] == "https://x"


def test_nested_shape():
    items = [
        {
            "id": "1",
            "content": {
                "title": "Nested",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "https://news"},
                "pubDate": "2026-11-19T10:00:00Z",
                "summary": "S",
            },
        }
    ]
    out = normalise_articles(items, 5)
    assert out[0] == {
        "title": "Nested",
        "publisher": "Reuters",
        "link": "https://news",
        "published_date": "2026-11-19T10:00:00Z",
        "summary": "S",
    }


def test_limit_applied():
    assert len(normalise_articles([{"title": "x"}] * 5, 2)) == 2
