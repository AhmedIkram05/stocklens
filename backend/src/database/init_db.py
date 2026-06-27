"""
Run Alembic migrations at application startup.

Wraps Alembic's ``command.upgrade`` inside ``asyncio.to_thread`` so it can
be called from FastAPI's async lifespan without blocking the event loop.
"""

import asyncio

from alembic.command import upgrade
from alembic.config import Config


async def run_migrations() -> None:
    """Run all pending Alembic migrations."""
    alembic_cfg = Config("alembic.ini")
    await asyncio.to_thread(upgrade, alembic_cfg, "head")
