"""
Redis connection pool and token blacklist helpers.

Provides a singleton ``redis.asyncio`` connection pool used by the auth
module for JTI blacklisting and by rate-limiters for counter storage.
"""

from __future__ import annotations

import structlog
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.connection import parse_url

from src.config import settings

logger = structlog.get_logger()

_pool: ConnectionPool | None = None


async def get_redis() -> Redis:
    """Return a Redis client backed by a shared connection pool."""
    global _pool
    if _pool is None:
        url_kwargs = parse_url(settings.REDIS_URL)
        if settings.REDIS_URL.startswith("rediss://"):
            # ElastiCache uses AWS-managed self-signed certs —
            # skip client-side verification (cannot pin a cert that rotates).
            url_kwargs["ssl_cert_reqs"] = None
        _pool = ConnectionPool(**url_kwargs)
        logger.info("redis_pool_initialised", url=settings.REDIS_URL)
    return Redis(connection_pool=_pool)


async def close_redis() -> None:
    """Close the global Redis connection pool."""
    global _pool
    if _pool:
        await _pool.disconnect()
        _pool = None
        logger.info("redis_pool_closed")


# ── Token blacklist ───────────────────────────────────────────────────────────


async def blacklist_token(jti: str, ttl: int) -> None:
    """Add a JWT ID to the Redis blacklist with the given TTL (seconds).

    Once a token expires naturally the blacklist entry will auto-expire,
    keeping Redis memory usage bounded.

    Gracefully degrades: if Redis is unavailable, logs a warning and skips
    blacklisting so the request succeeds.
    """
    try:
        r = await get_redis()
        await r.set(f"bl:{jti}", "1", ex=ttl)
    except Exception:
        logger.warning("redis_blacklist_failed", jti=jti[:8], exc_info=True)


async def is_token_blacklisted(jti: str) -> bool:
    """Return ``True`` if the JWT ID has been blacklisted.

    Gracefully degrades: if Redis is unavailable, returns ``False`` and logs
    a warning so the request proceeds without blacklist checking.
    """
    try:
        r = await get_redis()
        return await r.exists(f"bl:{jti}") > 0
    except Exception:
        logger.warning("redis_blacklist_check_failed", jti=jti[:8], exc_info=True)
        return False


# ── Rate-limit counter helpers (optional, slowapi usually handles this) ──────


async def increment_rate_limit(key: str, window: int) -> int:
    """Increment a sliding-window counter and return the current count."""
    r = await get_redis()
    pipe = r.pipeline()
    pipe.incr(f"rl:{key}")
    pipe.expire(f"rl:{key}", window)
    result = await pipe.execute()
    return int(result[0])


async def get_rate_limit(key: str) -> int:
    """Return the current count for a rate-limit key (0 if absent)."""
    r = await get_redis()
    val = await r.get(f"rl:{key}")
    return int(val) if val is not None else 0
