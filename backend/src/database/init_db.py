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

    Silently ignores failures caused by concurrent workers racing on
    startup — if another worker already applied the migration, this is
    a no-op rather than a crash.
    """
    alembic_cfg = Config("alembic.ini")
    try:
        await asyncio.to_thread(upgrade, alembic_cfg, "head")
    except ProgrammingError:
        logger.info("Migration already applied by another worker")
    except Exception as exc:
        logger.warning("Migration failed (non-fatal): %s", exc)
