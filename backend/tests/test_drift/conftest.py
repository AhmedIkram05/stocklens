"""Shared fixtures and configuration for drift module tests.

Tests that require ``evidently`` will skip if the package is not installed.
Pure numpy/scipy tests (service, repository) run unconditionally.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def mock_connection_ctx() -> AsyncMock:
    """Mock the database connection context manager.

    Provides a mock ``connection_ctx`` that returns a mock async connection
    with ``fetchrow``, ``fetch``, ``fetchval``, and ``execute`` methods.
    """
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value="DELETE 0")

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    patcher = patch("src.drift.repository.connection_ctx", return_value=mock_cm)
    patcher.start()
    yield mock_conn
    patcher.stop()
