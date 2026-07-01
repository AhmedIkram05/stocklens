"""
Tests for the Redis cache helpers.

These tests mock the Redis client to avoid needing a live Redis instance.
The functions under test gracefully degrade when Redis is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from src.cache.redis import blacklist_token, is_token_blacklisted


class TestBlacklistToken:
    """Tests for ``blacklist_token``."""

    @patch("src.cache.redis.get_redis", autospec=True)
    async def test_blacklist_success(self, mock_get_redis):
        """Blacklisting a token sets a Redis key with TTL."""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        await blacklist_token("test-jti-123", 3600)

        mock_redis.set.assert_called_once_with("bl:test-jti-123", "1", ex=3600)

    @patch("src.cache.redis.get_redis", autospec=True)
    async def test_blacklist_graceful_degradation(self, mock_get_redis):
        """When Redis is down, blacklist_token logs a warning and does not raise."""
        mock_get_redis.side_effect = ConnectionError("Redis unavailable")

        # Should not raise
        await blacklist_token("test-jti-456", 3600)


class TestIsTokenBlacklisted:
    """Tests for ``is_token_blacklisted``."""

    @patch("src.cache.redis.get_redis", autospec=True)
    async def test_token_is_blacklisted(self, mock_get_redis):
        """Returns True when the token exists in Redis."""
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 1
        mock_get_redis.return_value = mock_redis

        result = await is_token_blacklisted("test-jti-789")
        assert result is True
        mock_redis.exists.assert_called_once_with("bl:test-jti-789")

    @patch("src.cache.redis.get_redis", autospec=True)
    async def test_token_not_blacklisted(self, mock_get_redis):
        """Returns False when the token does not exist in Redis."""
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0
        mock_get_redis.return_value = mock_redis

        result = await is_token_blacklisted("test-jti-abc")
        assert result is False

    @patch("src.cache.redis.get_redis", autospec=True)
    async def test_check_graceful_degradation(self, mock_get_redis):
        """When Redis is down, returns False (skips blacklist check)."""
        mock_get_redis.side_effect = ConnectionError("Redis unavailable")

        result = await is_token_blacklisted("test-jti-def")
        assert result is False


class TestRateLimitHelpers:
    """Tests for the rate-limit counter helpers."""

    @patch("src.cache.redis.get_redis")
    async def test_increment_rate_limit(self, mock_get_redis):
        """Incrementing a rate-limit counter works."""
        from src.cache.redis import increment_rate_limit

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.incr.return_value = None
        mock_pipe.expire.return_value = None
        mock_pipe.execute = AsyncMock(return_value=[3])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_get_redis.return_value = mock_redis

        result = await increment_rate_limit("test-key", 60)
        assert result == 3

    @patch("src.cache.redis.get_redis")
    async def test_get_rate_limit(self, mock_get_redis):
        """Getting a rate-limit counter returns 0 for unseen keys."""
        from src.cache.redis import get_rate_limit

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis

        result = await get_rate_limit("unknown-key")
        assert result == 0
