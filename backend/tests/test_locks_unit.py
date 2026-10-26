"""DB-free unit tests for the shared per-portfolio lock helpers.

These pin the two properties that keep the M11 invariant from becoming an
unbounded wait: the lock is *try*-acquired (never a blocking
``pg_advisory_xact_lock``), and the write wrapper reuses an already-open
transaction instead of letting asyncpg reject a manually started one.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src import locks


class _LockConn:
    """Records the statements it is asked to run; returns scripted results."""

    def __init__(self, results: list[bool]) -> None:
        self._results = list(results)
        self.queries: list[str] = []

    async def fetchval(self, query: str, *_args, **_kwargs) -> bool:
        self.queries.append(query)
        return self._results.pop(0) if self._results else False


async def test_lock_portfolio_uses_try_lock_and_returns_when_granted():
    conn = _LockConn([True])
    await locks.lock_portfolio(conn, "11111111-1111-1111-1111-111111111111")
    assert len(conn.queries) == 1
    # A blocking pg_advisory_xact_lock here is the bug this replaces.
    assert "pg_try_advisory_xact_lock" in conn.queries[0]
    assert "pg_advisory_xact_lock(" not in conn.queries[0]


async def test_lock_portfolio_gives_up_with_409(monkeypatch):
    monkeypatch.setattr(locks, "_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(locks, "_LOCK_POLL_SECONDS", 0.0)
    conn = _LockConn([])  # never granted
    with pytest.raises(HTTPException) as excinfo:
        await locks.lock_portfolio(conn, "11111111-1111-1111-1111-111111111111")
    assert excinfo.value.status_code == 409
    assert conn.queries  # it tried at least once before giving up


class _RecordingTx:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self):
        self._log.append("begin")

    async def __aexit__(self, *_exc):
        self._log.append("end")


class _WriteConn:
    def __init__(self, in_transaction: bool, log: list[str]) -> None:
        self._in_transaction = in_transaction
        self._log = log

    def is_in_transaction(self) -> bool:
        return self._in_transaction

    def transaction(self) -> _RecordingTx:
        return _RecordingTx(self._log)


async def test_portfolio_write_reuses_open_transaction():
    log: list[str] = []
    conn = _WriteConn(in_transaction=True, log=log)
    async with locks.portfolio_write(conn) as yielded:
        assert yielded is conn
    # No BEGIN/COMMIT issued — the caller's transaction is reused.
    assert log == []


async def test_portfolio_write_opens_transaction_when_autocommit():
    log: list[str] = []
    conn = _WriteConn(in_transaction=False, log=log)
    async with locks.portfolio_write(conn) as yielded:
        assert yielded is conn
    assert log == ["begin", "end"]
