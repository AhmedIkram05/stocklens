"""
Tests for the auth module (register, login, refresh, logout, me).

All database access runs inside the per-test transaction provided by
``conftest._test_db`` so no data leaks between tests.
"""

from __future__ import annotations

from httpx import AsyncClient

# ── Register ───────────────────────────────────────────────────────────────────


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        """Registering with valid data returns 201 and a token pair."""
        response = await client.post(
            "/auth/register",
            json={
                "email": "alice@example.com",
                "password": "SecurePass123!",
                "full_name": "Alice",
            },
        )
        assert response.status_code == 201
        data = response.json()

        assert "user" in data
        assert data["user"]["email"] == "alice@example.com"
        assert data["user"]["display_name"] == "Alice"
        assert "id" in data["user"]

        assert "tokens" in data
        assert data["tokens"]["token_type"] == "bearer"
        assert len(data["tokens"]["access_token"]) > 0
        assert len(data["tokens"]["refresh_token"]) > 0
        assert data["tokens"]["expires_in"] > 0

    async def test_register_duplicate_email(self, client: AsyncClient):
        """Registering with an existing email returns 409."""
        await client.post(
            "/auth/register",
            json={
                "email": "dup@example.com",
                "password": "SecurePass123!",
                "full_name": "First",
            },
        )
        response = await client.post(
            "/auth/register",
            json={
                "email": "dup@example.com",
                "password": "SecurePass456!",
                "full_name": "Second",
            },
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    async def test_register_invalid_email(self, client: AsyncClient):
        """Registering with an invalid email returns 422."""
        response = await client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "SecurePass123!",
                "full_name": "Bad Email",
            },
        )
        assert response.status_code == 422

    async def test_register_short_password(self, client: AsyncClient):
        """Registering with a password < 8 chars returns 422."""
        response = await client.post(
            "/auth/register",
            json={
                "email": "short@example.com",
                "password": "Ab1",
                "full_name": "Short Pwd",
            },
        )
        assert response.status_code == 422

    async def test_register_normalises_email(self, client: AsyncClient):
        """Email is lower-cased and stripped during registration."""
        response = await client.post(
            "/auth/register",
            json={
                "email": "  Alice@Example.COM  ",
                "password": "SecurePass123!",
                "full_name": "Alice",
            },
        )
        assert response.status_code == 201
        assert response.json()["user"]["email"] == "alice@example.com"


# ── Login ──────────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        """Logging in with valid credentials returns 200 and a token pair."""
        await client.post(
            "/auth/register",
            json={
                "email": "bob@example.com",
                "password": "SecurePass123!",
                "full_name": "Bob",
            },
        )
        response = await client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "SecurePass123!"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["user"]["email"] == "bob@example.com"
        assert "access_token" in data["tokens"]
        assert "refresh_token" in data["tokens"]

    async def test_login_wrong_password(self, client: AsyncClient):
        """Logging in with wrong password returns 401."""
        await client.post(
            "/auth/register",
            json={
                "email": "wrong@example.com",
                "password": "SecurePass123!",
                "full_name": "Wrong",
            },
        )
        response = await client.post(
            "/auth/login",
            json={"email": "wrong@example.com", "password": "WrongPassword!"},
        )
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Logging in with an unregistered email returns 401."""
        response = await client.post(
            "/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "DoesNotMatter!",
            },
        )
        assert response.status_code == 401

    async def test_login_normalises_email(self, client: AsyncClient):
        """Email is lower-cased before lookup."""
        await client.post(
            "/auth/register",
            json={
                "email": "case@example.com",
                "password": "SecurePass123!",
                "full_name": "Case",
            },
        )
        response = await client.post(
            "/auth/login",
            json={"email": "CASE@EXAMPLE.COM", "password": "SecurePass123!"},
        )
        assert response.status_code == 200


# ── Get Me ─────────────────────────────────────────────────────────────────────


class TestGetMe:
    async def test_get_me_authenticated(self, client: AsyncClient, auth_headers: dict[str, str]):
        """GET /auth/me returns the authenticated user's profile."""
        response = await client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@stocklens.dev"
        assert "id" in data
        assert "display_name" in data

    async def test_get_me_unauthenticated(self, client: AsyncClient):
        """GET /auth/me without a token returns 401."""
        response = await client.get("/auth/me")
        assert response.status_code == 401
        assert "authentication required" in response.json()["detail"].lower()

    async def test_get_me_expired_token(self, client: AsyncClient):
        """GET /auth/me with an obviously fake token returns 401."""
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer this.is.a.fake.jwt.token"},
        )
        assert response.status_code == 401


# ── Refresh ────────────────────────────────────────────────────────────────────


class TestRefresh:
    async def test_refresh_success(self, client: AsyncClient):
        """Refreshing a valid token returns a new token pair."""
        reg = await client.post(
            "/auth/register",
            json={
                "email": "refresh@example.com",
                "password": "SecurePass123!",
                "full_name": "Refresh",
            },
        )
        old_refresh = reg.json()["tokens"]["refresh_token"]

        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0
        assert len(data["refresh_token"]) > 0
        assert data["refresh_token"] != old_refresh  # rotation

    async def test_refresh_rotation_revokes_old(self, client: AsyncClient):
        """After refresh, the old refresh token is revoked and cannot be reused."""
        reg = await client.post(
            "/auth/register",
            json={
                "email": "rotate@example.com",
                "password": "SecurePass123!",
                "full_name": "Rotate",
            },
        )
        old_refresh = reg.json()["tokens"]["refresh_token"]

        # First refresh — succeeds
        resp1 = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp1.status_code == 200

        # Second refresh with the same (now-revoked) token — must fail
        resp2 = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp2.status_code == 401
        assert "revoked" in resp2.json()["detail"].lower()

    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Refreshing with a garbage token returns 401."""
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": "garbage-token"},
        )
        assert response.status_code == 401

    async def test_refresh_with_access_token(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Using an access token (not refresh) on /refresh returns 401."""
        # auth_headers fixture registers a user and returns Bearer header
        # We need to extract the access token
        access = auth_headers["Authorization"].replace("Bearer ", "")
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": access},
        )
        assert response.status_code == 401


# ── Logout ─────────────────────────────────────────────────────────────────────


class TestLogout:
    async def test_logout_success(
        self, client: AsyncClient, auth_headers: dict[str, str], refresh_token: str
    ):
        """Logging out with valid auth returns 204."""
        response = await client.post(
            "/auth/logout",
            json={"refresh_token": refresh_token},
            headers=auth_headers,
        )
        assert response.status_code == 204

    async def test_logout_then_me_fails(self, client: AsyncClient):
        """After logout, the same access token is rejected by /me."""
        reg = await client.post(
            "/auth/register",
            json={
                "email": "logout@example.com",
                "password": "SecurePass123!",
                "full_name": "Logout",
            },
        )
        access = reg.json()["tokens"]["access_token"]
        refresh = reg.json()["tokens"]["refresh_token"]
        headers = {"Authorization": f"Bearer {access}"}

        # Logout — blacklists the access token + revokes refresh token
        logout_resp = await client.post(
            "/auth/logout",
            json={"refresh_token": refresh},
            headers=headers,
        )
        assert logout_resp.status_code == 204

        # Same token should now be rejected
        me_resp = await client.get("/auth/me", headers=headers)
        assert me_resp.status_code == 401
        assert "revoked" in me_resp.json()["detail"].lower()

    async def test_logout_unauthenticated(self, client: AsyncClient):
        """Logout without a token returns 401."""
        response = await client.post("/auth/logout")
        assert response.status_code == 401

    async def test_logout_refresh_revoked(
        self, client: AsyncClient, auth_headers: dict[str, str], refresh_token: str
    ):
        """After logout, the refresh token is revoked and cannot be used to refresh."""
        await client.post(
            "/auth/logout",
            json={"refresh_token": refresh_token},
            headers=auth_headers,
        )

        # Trying to refresh with the revoked token should fail
        refresh_resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 401
