"""
Shared slowapi Limiter instance.

Both ``main.py`` and ``receipts/router.py`` need access to the same
``Limiter`` instance so that rate-limit counters are shared globally.
Placing it in its own module avoids the circular import that would occur
if ``router.py`` imported from ``main.py`` (since ``main.py`` imports the
router before ``app.state.limiter`` is set).

Storage uses Redis (via the ``limits`` library's ``storage_from_string``)
with an in-memory fallback so rate limiting gracefully degrades when
Redis is unavailable.
"""

import asyncio
import inspect

# slowapi uses ``asyncio.iscoroutinefunction`` which is deprecated in Python 3.14+
# and slated for removal in 3.16. ``asyncio.iscoroutinefunction`` is an alias for
# ``inspect.iscoroutinefunction`` — redirect it so slowapi uses the canonical API.
asyncio.iscoroutinefunction = inspect.iscoroutinefunction

from slowapi import Limiter  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402

from src.config import settings  # noqa: E402

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
)
