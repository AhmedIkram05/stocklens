"""Unit tests for auth/dependencies.py — get_current_user, require_active_user.

Uses FastAPI's TestClient with dependency overrides to avoid needing a real DB.
Mocks Redis (is_token_blacklisted) and the database (connection_ctx).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.auth.dependencies import get_current_user, require_active_user
from src.auth.schemas import UserInDB
from src.auth.utils import create_access_token

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_app(dependency):
    """Build a minimal FastAPI app with one endpoint testing *dependency*."""
    app = FastAPI()

    @app.get("/me")
    async def me(user=Depends(dependency)):
        return {"id": user.id, "email": user.email, "is_active": user.is_active}

    return app


def _mock_user(**kwargs: object) -> UserInDB:
    now = datetime.now(timezone.utc)
    defaults: dict[str, object] = dict(
        id="u1",
        email="test@test.com",
        password_hash="$2b$12$abc123",
        display_name="Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return UserInDB(**defaults)  # type: ignore[arg-type]


# ── get_current_user ───────────────────────────────────────────────────────────


class TestGetCurrentUser:
    """Tests get_current_user by overriding the DB + Redis dependencies."""

    def test_missing_auth_header_returns_401(self):
        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"

    def test_expired_token_returns_401(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        # Create an expired token directly
        from datetime import datetime, timezone

        expired_token = pyjwt.encode(
            {
                "sub": "u1",
                "jti": "expired",
                "exp": int(datetime.now(timezone.utc).timestamp()) - 1,
                "iat": int(datetime.now(timezone.utc).timestamp()) - 3600,
                "type": "access",
            },
            "test-secret",
            algorithm="HS256",
        )

        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token has expired"

    def test_invalid_token_returns_401(self):
        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": "Bearer definitely-not-a-valid-token"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid token"

    def test_refresh_token_type_rejected(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)

        from src.auth.utils import create_refresh_token

        ref_token, _ = create_refresh_token("u1")
        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {ref_token}"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid token type"

    @patch("src.auth.dependencies.is_token_blacklisted", new_callable=AsyncMock)
    def test_blacklisted_token_returns_401(self, mock_blacklist, monkeypatch):
        mock_blacklist.return_value = True
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        token, _ = create_access_token("u1")

        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token has been revoked"

    @patch("src.auth.dependencies.is_token_blacklisted", new_callable=AsyncMock)
    @patch("src.auth.dependencies.connection_ctx")
    def test_user_not_found_returns_401(self, mock_ctx, mock_blacklist, monkeypatch):
        mock_blacklist.return_value = False
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        # Mock DB connection returning no rows
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_ctx.return_value = mock_cm

        token, _ = create_access_token("nonexistent-user")

        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not found"

    @patch("src.auth.dependencies.is_token_blacklisted", new_callable=AsyncMock)
    @patch("src.auth.dependencies.connection_ctx")
    def test_valid_user_returns_200(self, mock_ctx, mock_blacklist, monkeypatch):
        mock_blacklist.return_value = False
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        # Mock DB returning a valid user row
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        class MockRow:
            def __getitem__(self, key):
                return {
                    "id": "u1",
                    "email": "test@test.com",
                    "password_hash": "$2b$12$hash",
                    "display_name": "Test User",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }[key]

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = MockRow()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_ctx.return_value = mock_cm

        token, _ = create_access_token("u1")

        app = _make_app(get_current_user)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "u1"
        assert data["email"] == "test@test.com"
        assert data["is_active"] is True


# ── get_current_user_id ────────────────────────────────────────────────────────


class TestGetCurrentUserId:
    async def test_returns_id_string(self, monkeypatch):
        from src.auth.dependencies import get_current_user_id

        user = _mock_user(id="user-abc")
        result = await get_current_user_id(user)
        assert result == "user-abc"


# ── require_active_user ────────────────────────────────────────────────────────


class TestRequireActiveUser:
    async def test_active_user_passes(self):
        user = _mock_user(is_active=True)
        result = await require_active_user(user)
        assert result is user

    def test_deactivated_user_raises_403(self):
        user = _mock_user(is_active=False)

        app = _make_app(lambda: user)  # bypass auth, inject inactive user
        # Override to always return inactive user
        app.dependency_overrides[require_active_user] = lambda: user

        # Use a dummy endpoint wrapped with require_active_user
        test_app = FastAPI()

        @test_app.get("/protected")
        async def protected(u=Depends(require_active_user)):
            return {"status": "ok"}

        test_app.dependency_overrides[get_current_user] = lambda: user

        client2 = TestClient(test_app)
        resp = client2.get("/protected")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Account is deactivated"

    def test_active_user_passes_through(self):
        user = _mock_user(is_active=True)

        test_app = FastAPI()

        @test_app.get("/protected")
        async def protected(u=Depends(require_active_user)):
            return {"id": u.id}

        test_app.dependency_overrides[get_current_user] = lambda: user

        client = TestClient(test_app)
        resp = client.get("/protected")
        assert resp.status_code == 200
        assert resp.json()["id"] == "u1"
