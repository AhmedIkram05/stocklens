"""
Alembic environment configuration — async mode using asyncpg.

Production Docker images ship with asyncpg (not psycopg2). We run the
migration inside ``asyncio.run()`` which is safe here because Alembic loads
this module either from the main thread (production bootstrap) or from an
``asyncio.to_thread`` worker (test fixture on Python 3.12+ where
SQLAlchemy's async driver + greenlet works without nesting issues).

If you hit greenlet errors locally, run the migration directly::

    PYTHONPATH=. alembic upgrade head
"""

from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from src.config import settings
from src.database.schema import target_metadata

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Set up Python logging from the [loggers] section in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations with a live async connection.

    Tests run against the isolated ``postgres_test`` database, so when the
    environment is ``test`` we migrate there instead of the runtime DB.
    """
    dsn = settings.TEST_DATABASE_URL if settings.ENVIRONMENT == "test" else settings.DATABASE_URL
    connectable = create_async_engine(
        dsn,
    )
    async with connectable.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await connectable.dispose()


def do_run_migrations(connection):
    """Configure the migration context and run all pending revisions."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
