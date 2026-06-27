"""
Shared slowapi Limiter instance.

Both ``main.py`` and ``receipts/router.py`` need access to the same
``Limiter`` instance so that rate-limit counters are shared globally.
Placing it in its own module avoids the circular import that would occur
if ``router.py`` imported from ``main.py`` (since ``main.py`` imports the
router before ``app.state.limiter`` is set).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
