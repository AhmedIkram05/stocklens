"""Login/register hardening: bcrypt off-loop, constant-time unknown email, bounds."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.auth.schemas import LoginRequest, RegisterRequest


class _FakeConn:
    def __init__(self, user):
        self.user = user
        self.executed = []

    async def fetchrow(self, query, *args):
        return self.user

    async def execute(self, query, *args):
        self.executed.append(args)
        return "INSERT 0 1"


class _FakeCtx:
    def __init__(self, conn):
        self.conn = conn

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return False


def _user(password_hash: str = "stored-hash", is_active: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "user@example.com",
        "password_hash": password_hash,
        "display_name": "User",
        "is_active": is_active,
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.asyncio
async def test_login_unknown_email_still_verifies_once(monkeypatch):
    """An unknown account must not short-circuit before bcrypt (timing oracle)."""
    from src.auth import router as auth_router

    verify = AsyncMock(return_value=False)
    monkeypatch.setattr(auth_router, "verify_password_async", verify)

    with patch("src.auth.router.connection_ctx", _FakeCtx(_FakeConn(None))):
        with pytest.raises(HTTPException) as exc:
            await auth_router.login.__wrapped__(
                request=object(),
                body=LoginRequest(email="missing@example.com", password="password123"),
            )

    assert exc.value.status_code == 401
    verify.assert_awaited_once_with("password123", None)


@pytest.mark.asyncio
async def test_login_known_email_verifies_stored_hash(monkeypatch):
    from src.auth import router as auth_router

    verify = AsyncMock(return_value=False)
    monkeypatch.setattr(auth_router, "verify_password_async", verify)

    user = _user(password_hash="stored-hash")
    with patch("src.auth.router.connection_ctx", _FakeCtx(_FakeConn(user))):
        with pytest.raises(HTTPException) as exc:
            await auth_router.login.__wrapped__(
                request=object(),
                body=LoginRequest(email="user@example.com", password="wrong-password"),
            )

    assert exc.value.status_code == 401
    verify.assert_awaited_once_with("wrong-password", "stored-hash")


@pytest.mark.asyncio
async def test_login_success_returns_tokens(monkeypatch):
    from src.auth import router as auth_router

    monkeypatch.setattr(auth_router, "verify_password_async", AsyncMock(return_value=True))

    with patch("src.auth.router.connection_ctx", _FakeCtx(_FakeConn(_user()))):
        result = await auth_router.login.__wrapped__(
            request=object(),
            body=LoginRequest(email="user@example.com", password="password123"),
        )

    assert result.user.email == "user@example.com"
    assert result.tokens.access_token
    assert result.tokens.refresh_token


@pytest.mark.asyncio
async def test_register_uses_async_hash(monkeypatch):
    from src.auth import router as auth_router

    hashed = AsyncMock(return_value="new-hash")
    monkeypatch.setattr(auth_router, "hash_password_async", hashed)

    with patch(
        "src.auth.router.connection_ctx",
        _FakeCtx(_FakeConn(_user(password_hash="new-hash"))),
    ):
        result = await auth_router.register.__wrapped__(
            request=object(),
            body=RegisterRequest(
                email="user@example.com",
                password="password123",
                full_name="User",
            ),
        )

    hashed.assert_awaited_once_with("password123")
    assert result.user.email == "user@example.com"


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409():
    from src.auth import router as auth_router

    with patch("src.auth.router.connection_ctx", _FakeCtx(_FakeConn(None))):
        with pytest.raises(HTTPException) as exc:
            await auth_router.register.__wrapped__(
                request=object(),
                body=RegisterRequest(
                    email="user@example.com",
                    password="password123",
                    full_name="User",
                ),
            )

    assert exc.value.status_code == 409


def test_register_full_name_is_bounded():
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            password="password123",
            full_name="x" * 101,
        )

    RegisterRequest(
        email="user@example.com",
        password="password123",
        full_name="x" * 100,
    )


def test_login_password_is_bounded():
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password="x" * 129)
