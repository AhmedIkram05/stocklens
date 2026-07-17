"""Override root conftest DB fixtures for ML tests that need no database."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _migrate_db() -> None:
    """No-op: ML tests don't need a database."""
    return None


@pytest.fixture(autouse=True)
def _test_db() -> None:
    """No-op: ML tests don't need a database."""
    return None


@pytest.fixture(autouse=True)
def _setup_app() -> None:
    """No-op: ML tests don't need a database."""
    return None
