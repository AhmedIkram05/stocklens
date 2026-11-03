"""Alembic migration chain integrity — structural, no database.

The migration chain cannot be exercised with SQLite: ``0001`` and later use
Postgres-only DDL (``JSONB``, ``gen_random_uuid()``, GIN indexes,
``ADD COLUMN IF NOT EXISTS``), so an in-memory upgrade/downgrade round-trip is
not portable. The CI backend job instead runs ``alembic upgrade head`` against
a real Postgres service before pytest. What is testable without a DB is that
the chain is intact — one head, linear, unambiguous — and that every revision
module imports and defines its ``upgrade``/``downgrade`` hooks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory(str(ALEMBIC_DIR))


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


@pytest.mark.skip(
    reason="chain uses Postgres-only DDL (JSONB, gen_random_uuid(), GIN indexes, "
    "ADD COLUMN IF NOT EXISTS) — no SQLite round-trip; validated structurally above "
    "and by `alembic upgrade head` against Postgres in CI"
)
def test_upgrade_downgrade_round_trip_on_sqlite():
    """Placeholder documenting why the round-trip lives in CI, not here."""
