"""
Alembic environment configuration — sync mode using psycopg2.

Loads DATABASE_URL from src.config.settings and strips the async driver
suffix so Alembic can use a plain sync connection.  No asyncio, no
greenlet — just a direct psycopg2 connection.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context
from src.config import settings
from src.database.schema import target_metadata

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Use a sync-compatible URL (psycopg2 is already a project dependency).
sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2", 1)
config.set_main_option("sqlalchemy.url", sync_url)

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


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a sync engine (psycopg2)."""
    db_url = config.get_main_option("sqlalchemy.url")
    assert db_url is not None, "sqlalchemy.url must be set"
    connectable = create_engine(db_url)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
