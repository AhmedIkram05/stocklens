"""
pytest fixtures for the StockLens backend test suite.

Uses the ``postgres_test`` Docker container for database isolation.
Each test that touches the database runs inside a transaction that is
rolled back on teardown.

Transaction isolation is achieved by monkey-patching
:func:`src.database.connection.get_conn` so that every query made by the
application code reuses the same connection currently inside a ``BEGIN`` /
``ROLLBACK`` block.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.database import connection as db_conn
from src.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Use the same event loop for the entire session."""
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def _test_db() -> AsyncGenerator[None, None]:
    """Run each test inside a transaction that is rolled back on teardown.

    Opens a direct connection to the test database, starts a ``BEGIN``, then
    monkey-patches :func:`connection.get_conn` so that any query made through
    the application's asyncpg pool reuses this connection.

    On teardown the transaction is rolled back and the original functions are
    restored.
    """
    dsn = settings.TEST_DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    conn = await asyncpg.connect(dsn)
    await conn.execute("BEGIN")

    # Save originals
    original_get_conn = db_conn.get_conn
    original_release_conn = db_conn.release_conn

    async def _patched_get_conn() -> asyncpg.Connection:
        return conn

    async def _patched_release_conn(_c: asyncpg.Connection) -> None:
        pass  # Connection is managed by this fixture

    db_conn.get_conn = _patched_get_conn
    db_conn.release_conn = _patched_release_conn

    try:
        yield
    finally:
        # Restore originals
        db_conn.get_conn = original_get_conn
        db_conn.release_conn = original_release_conn

        await conn.execute("ROLLBACK")
        await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def _setup_app() -> AsyncGenerator[None, None]:
    """Initialise the asyncpg pool before tests and tear it down after."""
    await db_conn.init_pool(settings.TEST_DATABASE_URL, min_size=1, max_size=2)
    try:
        yield
    finally:
        await db_conn.close_pool()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Return an async HTTP client pointed at the FastAPI app.

    Runs the lifespan startup (migrations, pool init) before yielding,
    then shuts down after the test completes.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a test user and return ``Authorization`` headers.

    The user is created with email ``test@stocklens.test`` and password
    ``TestPass123!``.
    """
    response = await client.post(
        "/auth/register",
        json={
            "email": "test@stocklens.test",
            "password": "TestPass123!",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    token = data["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def refresh_token(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    """Return a valid refresh token for the test user by logging in.

    Depends on ``auth_headers`` so the test user is already registered.
    """
    response = await client.post(
        "/auth/login",
        json={
            "email": "test@stocklens.test",
            "password": "TestPass123!",
        },
    )
    assert response.status_code == 200
    return response.json()["tokens"]["refresh_token"]
