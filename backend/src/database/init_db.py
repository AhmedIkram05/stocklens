"""
Run Alembic migrations at application startup.

Wraps Alembic's ``command.upgrade`` inside ``asyncio.to_thread`` so it can
be called from FastAPI's async lifespan without blocking the event loop.
"""

import asyncio
import logging

from alembic.command import upgrade
from alembic.config import Config
from sqlalchemy.exc import ProgrammingError

logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    """Run all pending Alembic migrations.

    Only ignores :class:`ProgrammingError` which occurs when two workers
    race on startup — the second one sees the version table already
    populated and fails harmlessly.  All other errors are propagated so
    CI (and local dev) never silently skips a failed migration.
    """
    alembic_cfg = Config("alembic.ini")
    try:
        await asyncio.to_thread(upgrade, alembic_cfg, "head")
    except ProgrammingError:
        logger.info("Migration already applied by another worker")
