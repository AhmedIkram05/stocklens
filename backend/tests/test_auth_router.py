"""REST /auth/refresh rotation — atomic single-use claim (DB-free).

Mirrors the MCP-side concurrency tests in test_mcp_auth.py: the claim is a
single conditional UPDATE, so two concurrent refreshes of the same token can
never both mint. The slowapi limiter is bypassed via ``__wrapped__`` — the
rate limit is orthogonal to rotation semantics.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.auth.schemas import TokenPayload
from src.auth.utils import create_refresh_token, decode_token, hash_token


class _FakeRefreshConn:
    """In-memory refresh_tokens emulating the atomic claim statement.

    The check-and-set inside ``fetchval`` is synchronous, i.e. atomic within
    one event-loop turn — exactly the guarantee the conditional UPDATE gives
    against two concurrent refreshes.
    """

    def __init__(self):
        self.tokens: dict[str, bool] = {}  # token_hash -> revoked
        self.claim_queries: list[str] = []
        self.new_inserts: list[tuple] = []
        self.revoked_all_for: list[str] = []

    def seed(self, token_hash: str) -> None:
        self.tokens[token_hash] = False

    async def fetchval(self, query, *args):
        if "UPDATE refresh_tokens" in query:
            self.claim_queries.append(query)
            assert "AND revoked = false" in query, "claim must be a conditional UPDATE"
            (token_hash,) = args
            if token_hash not in self.tokens or self.tokens[token_hash]:
                return None  # rowcount 0 → replay path
            self.tokens[token_hash] = True
            return True  # rowcount 1 → mint path
        if "SELECT revoked FROM refresh_tokens" in query:
            (token_hash,) = args
            if token_hash not in self.tokens:
                return None  # unknown token → plain 401
            return self.tokens[token_hash]  # already-revoked → stolen-token path
        raise AssertionError(f"unexpected fetchval: {query[:60]}")

    async def execute(self, query, *args):
        if "UPDATE refresh_tokens SET revoked = true WHERE user_id" in query:
            self.revoked_all_for.append(args[0])
            return "UPDATE 0"
        if "INSERT INTO refresh_tokens" in query:
            self.new_inserts.append(args)
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {query[:60]}")


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


def _seeded_conn(user: str = "user-race"):
    """Refresh token for *user* + a conn seeded with its hash."""
    refresh_token, _jti = create_refresh_token(user)
    payload: TokenPayload = decode_token(refresh_token)
    conn = _FakeRefreshConn()
    conn.seed(hash_token(payload.jti, payload.sub))
    return conn, refresh_token, payload


async def _call_refresh(conn, refresh_token):
    from src.auth.router import refresh

    body = type("B", (), {"refresh_token": refresh_token})()
    with (
        patch("src.auth.router.connection_ctx", _FakeCtx(conn)),
        patch("src.auth.router.is_token_blacklisted", new_callable=AsyncMock, return_value=False),
        patch("src.auth.router.blacklist_token", new_callable=AsyncMock),
    ):
        return await refresh.__wrapped__(request=object(), body=body)  # type: ignore[call-arg]


async def test_double_refresh_same_jti_second_takes_reuse_path():
    from fastapi import HTTPException

    conn, refresh_token, _payload = _seeded_conn()

    results = await asyncio.gather(
        _call_refresh(conn, refresh_token),
        _call_refresh(conn, refresh_token),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, BaseException)]
    http_errors = [r for r in results if isinstance(r, HTTPException)]
    assert len(successes) == 1, "only one refresh may mint a new pair"
    assert len(http_errors) == 1
    # The loser takes the stolen-token revoke-all path, not a plain not-found.
    assert http_errors[0].status_code == 401
    assert conn.revoked_all_for == ["user-race"]
    # Exactly one new refresh token was minted across both requests.
    assert len(conn.new_inserts) == 1
    # The claim is a single conditional UPDATE (no check-then-act SELECT first).
    assert conn.claim_queries
    for q in conn.claim_queries:
        assert "AND revoked = false" in q


async def test_unknown_refresh_token_401_without_revoke_all():
    from fastapi import HTTPException

    conn, refresh_token, payload = _seeded_conn()
    # The conn knows nothing about this token — the claim misses on not-found.
    conn.tokens.clear()

    with pytest.raises(HTTPException) as exc:
        await _call_refresh(conn, refresh_token)

    assert exc.value.status_code == 401
    # Unknown token must NOT trip the stolen-token revoke-all.
    assert conn.revoked_all_for == []
    assert len(conn.new_inserts) == 0


async def test_replayed_refresh_token_revokes_all_for_user():
    from fastapi import HTTPException

    conn, refresh_token, payload = _seeded_conn()
    # Token exists but is already revoked — a replay of a rotated token.
    conn.tokens[hash_token(payload.jti, payload.sub)] = True

    with pytest.raises(HTTPException) as exc:
        await _call_refresh(conn, refresh_token)

    assert exc.value.status_code == 401
    assert conn.revoked_all_for == [payload.sub]
    assert len(conn.new_inserts) == 0
