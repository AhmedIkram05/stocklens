"""Alembic migration integrity.

Structural checks need no database: one head, a linear unambiguous chain, and
every revision module imports and defines its ``upgrade``/``downgrade`` hooks.
The final test goes further and runs a real upgrade/downgrade round-trip
against a throwaway Postgres database.

SQLite is not an option for the round-trip: ``0001`` and later use
Postgres-only DDL (``JSONB``, ``gen_random_uuid()``, GIN indexes,
``ADD COLUMN IF NOT EXISTS``). The round-trip creates a temporary database on
the same server the rest of the suite uses and drops it afterwards, so it never
touches the shared test schema. When no PostgreSQL is reachable it skips
cleanly — pure-unit runs use ``--noconftest`` (which also sidesteps the autouse
DB fixtures) and stay green; CI provides the Postgres service, so the
round-trip runs for real there.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
ALEMBIC_INI = ALEMBIC_DIR.parent / "alembic.ini"

# ``base`` is not a valid downgrade target: revisions ``af46e8a08234`` and
# ``0001`` both DROP the same tables (``agent_conversations``,
# ``spending_categories``), so a full downgrade fails on the second drop.
# ``0008`` is the deepest target that reverts cleanly while still exercising
# the newest revisions' downgrade bodies.
DOWNGRADE_TARGET = "0008"


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory(str(ALEMBIC_DIR))


def _test_dsn() -> str:
    """The DSN the rest of the suite uses.

    ``conftest`` rewrites the docker ``postgres_test`` host to
    ``localhost:5433`` when it is loaded; under ``--noconftest`` the raw URL is
    used instead.
    """
    from src.config import settings

    return settings.TEST_DATABASE_URL


def _unreachable_reason() -> str | None:
    """Return why PostgreSQL is unusable, or ``None`` when it is reachable."""
    try:
        dsn = _test_dsn()
    except Exception as exc:  # settings needs .env / env vars to import
        return f"TEST_DATABASE_URL unavailable ({exc.__class__.__name__})"
    parsed = urlsplit(dsn)
    host, port = parsed.hostname or "localhost", parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2):
            return None
    except OSError as exc:
        return f"no PostgreSQL reachable at {host}:{port} (TEST_DATABASE_URL): {exc}"


_SKIP_REASON = _unreachable_reason()


def _as_asyncpg_dsn(dsn: str) -> str:
    """Strip the SQLAlchemy driver suffix so asyncpg can parse the URL."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _with_database(dsn: str, database: str) -> str:
    parsed = urlsplit(dsn)
    return parsed._replace(path=f"/{database}").geturl()


async def _create_database(admin_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_database(admin_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


def _revision(dsn: str) -> str | None:
    """Read ``alembic_version.version_num`` from ``dsn``."""

    async def _read() -> str | None:
        conn = await asyncpg.connect(_as_asyncpg_dsn(dsn))
        try:
            return await conn.fetchval("SELECT version_num FROM alembic_version")
        finally:
            await conn.close()

    return asyncio.run(_read())


class TestRevisionChain:
    def test_single_head(self):
        assert len(_script_directory().get_heads()) == 1, (
            "more than one head — a migration branch is unmerged"
        )

    def test_chain_is_linear_and_unambiguous(self):
        script = _script_directory()
        revisions = list(script.walk_revisions())
        parents = [rev.down_revision for rev in revisions]

        non_base_parents = [p for p in parents if p is not None]
        assert len(non_base_parents) == len(set(non_base_parents)), (
            "a revision has more than one child — the chain has branched"
        )
        # Exactly one root; every other revision points at a known parent.
        assert parents.count(None) == 1, "expected exactly one base revision"
        known = {rev.revision for rev in revisions}
        for parent in non_base_parents:
            assert parent in known, f"down_revision {parent!r} points at an unknown revision"

    def test_every_revision_module_imports_and_defines_hooks(self):
        script = _script_directory()
        for rev in script.walk_revisions():
            module = rev.module  # imports the migration file
            assert callable(getattr(module, "upgrade", None)), (
                f"{rev.revision} ({module.__name__}) has no upgrade()"
            )
            assert callable(getattr(module, "downgrade", None)), (
                f"{rev.revision} ({module.__name__}) has no downgrade()"
            )


@pytest.mark.integration
@pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")
def test_upgrade_head_then_downgrade_round_trip(monkeypatch):
    """Upgrade a throwaway database to head, then downgrade to 0008.

    Asserts the recorded revision after each direction, so a migration whose
    ``upgrade`` or ``downgrade`` raises (the failure mode the structural checks
    cannot see) fails here instead of in production.
    """
    from src.config import settings

    test_dsn = _test_dsn()
    temp_db = f"stocklens_migtest_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    temp_dsn = _with_database(test_dsn, temp_db)

    asyncio.run(_create_database(_as_asyncpg_dsn(test_dsn), temp_db))
    try:
        # env.py migrates TEST_DATABASE_URL when ENVIRONMENT == "test"; point
        # both at the throwaway database for the duration of this test.
        monkeypatch.setattr(settings, "ENVIRONMENT", "test")
        monkeypatch.setattr(settings, "TEST_DATABASE_URL", temp_dsn)

        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("script_location", str(ALEMBIC_DIR))

        upgrade(cfg, "head")
        assert _revision(temp_dsn) == _script_directory().get_current_head()

        downgrade(cfg, DOWNGRADE_TARGET)
        assert _revision(temp_dsn) == DOWNGRADE_TARGET
    finally:
        asyncio.run(_drop_database(_as_asyncpg_dsn(test_dsn), temp_db))
