"""
Alembic environment configuration — async mode using asyncpg.

Loads DATABASE_URL from src.config.settings so the single source of truth
in config.py is used for both the application and migrations.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from src.config import settings
from src.database.schema import target_metadata

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Override sqlalchemy.url with the value from pydantic settings.
# The placeholder in alembic.ini is never used directly.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging from the [loggers] section in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection).

    Each migration is rendered as a SQL script that can be reviewed or
    applied manually.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Wrap Alembic's sync context configuration for use inside run_sync."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine, run all pending migrations, then dispose."""
    connectable = create_async_engine(
        config.get_main_option("sqlalchemy.url"),
    )
    async with connectable.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
