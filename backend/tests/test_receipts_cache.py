"""Unit tests for receipts/cache.py — Redis-backed cache for LLM & enrichment.

Uses mocked Redis via @patch("src.cache.redis.get_redis"). All cache
functions degrade gracefully when Redis is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.receipts import cache

# ── _text_hash ──────────────────────────────────────────────────────────────────


class TestTextHash:
    """_text_hash returns first 16 hex chars of SHA-256 digest."""

    def test_returns_16_char_hex_string(self):
        result = cache._text_hash("hello world")
        assert isinstance(result, str)
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        assert cache._text_hash("test") == cache._text_hash("test")

    def test_different_inputs_produce_different_hashes(self):
        assert cache._text_hash("abc") != cache._text_hash("xyz")

    def test_empty_string_works(self):
        result = cache._text_hash("")
        assert len(result) == 16


# ── get_cached_llm / set_cached_llm ─────────────────────────────────────────────


class TestCachedLlm:
    """get_cached_llm and set_cached_llm use llm_cache: key with 24h TTL."""

    @patch("src.receipts.cache.get_redis")
    async def test_get_returns_none_when_missing(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis

        result = await cache.get_cached_llm("some text")
        assert result is None

    @patch("src.receipts.cache.get_redis")
    async def test_get_returns_parsed_dict_when_hit(self, mock_get_redis):
        import json

        mock_redis = AsyncMock()
        expected = {"total": 12.50, "merchant": "Test Store"}
        mock_redis.get.return_value = json.dumps(expected)
        mock_get_redis.return_value = mock_redis

        result = await cache.get_cached_llm("some text")
        assert result == expected

    @patch("src.receipts.cache.get_redis")
    @patch("src.config.settings")
    async def test_set_stores_with_ttl(self, mock_settings, mock_get_redis):
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_settings.LLM_CACHE_TTL = 86400

        data = {"total": 9.99, "merchant": "Coffee Shop"}
        await cache.set_cached_llm("receipt text", data)

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.await_args
        assert call_args[0][0].startswith("llm_cache:")
        assert call_args[1] is not None  # JSON string
        assert call_args.kwargs.get("ex") == 86400

    @patch("src.receipts.cache.get_redis")
    async def test_round_trip(self, mock_get_redis):
        """set_cached_llm followed by get_cached_llm returns the same data."""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        mock_redis.get.return_value = (
            '{"total": 5.0, "merchant": "Bakery"}'  # set_cached_llm stores JSON
        )

        result = await cache.get_cached_llm("some receipt")
        assert result == {"total": 5.0, "merchant": "Bakery"}


# ── set_enrich_status / get_enrich_status ───────────────────────────────────────


class TestEnrichStatus:
    """set_enrich_status and get_enrich_status use enrich_status: key."""

    @patch("src.receipts.cache.get_redis")
    @patch("src.config.settings")
    async def test_set_stores_with_ttl(self, mock_settings, mock_get_redis):
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_settings.ENRICH_STATUS_TTL = 3600

        await cache.set_enrich_status("receipt-123", "processing")

        mock_redis.set.assert_awaited_once_with("enrich_status:receipt-123", "processing", ex=3600)

    @patch("src.receipts.cache.get_redis")
    async def test_get_returns_none_when_missing(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis

        result = await cache.get_enrich_status("receipt-999")
        assert result is None

    @patch("src.receipts.cache.get_redis")
    async def test_get_returns_status(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "completed"
        mock_get_redis.return_value = mock_redis

        result = await cache.get_enrich_status("receipt-456")
        assert result == "completed"

    @patch("src.receipts.cache.get_redis")
    async def test_key_format(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        await cache.set_enrich_status("receipt-abc", "started")
        key = mock_redis.set.call_args[0][0]
        assert key == "enrich_status:receipt-abc"
