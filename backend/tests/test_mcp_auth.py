"""Tests for MCP OAuth helpers — PKCE, token helpers, verifier.

Ponytail: no redis mock bloat — tests hit pure functions or patch redis.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp.auth import _code_challenge_s256, _verify_pkce


def test_code_challenge_s256_rfc7636():
    # RFC 7636 Appendix B
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    # Correct challenge per RFC
    challenge = _code_challenge_s256(verifier)
    assert challenge == base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")


def test_verify_pkce_s256():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = _code_challenge_s256(verifier)
    assert _verify_pkce(verifier, challenge, "S256") is True
    assert _verify_pkce("wrong", challenge, "S256") is False


def test_verify_pkce_plain():
    assert _verify_pkce("hello", "hello", "plain") is True
    assert _verify_pkce("hello", "bye", "plain") is False


@pytest.mark.asyncio
async def test_oauth_issuer_derived_from_request():

    from src.mcp.auth import _issuer

    # Mock request
    # easier: use httpx client to get real request via endpoint
    # Instead directly test function with mock
    mock_req = type("R", (), {"base_url": "http://localhost:8000/"})()
    assert _issuer(mock_req) == "http://localhost:8000"

    mock_req2 = type("R", (), {"base_url": "https://api.stocklens.dev:443/"})()
    assert _issuer(mock_req2) == "https://api.stocklens.dev:443"


def test_oauth_protected_resource_url():
    from src.mcp.auth import _resource_url

    mock_req = type("R", (), {"base_url": "http://localhost:8000/"})()
    assert _resource_url(mock_req) == "http://localhost:8000/mcp"


@pytest.mark.asyncio
async def test_store_and_consume_code_in_memory():
    # Test the real helpers with mocked redis

    store: dict[str, str] = {}

    class FakeRedis:
        async def set(self, k, v, ex=None):
            store[k] = v

        async def get(self, k):
            return store.get(k)

        async def delete(self, k):
            store.pop(k, None)

    fake = FakeRedis()
    with patch("src.mcp.auth.get_redis", new_callable=AsyncMock, return_value=fake):
        from src.mcp.auth import _consume_code, _store_code

        await _store_code("code123", {"user_id": "u1", "scope": "mcp:tools"})
        data = await _consume_code("code123")
        assert data["user_id"] == "u1"
        # single-use
        assert await _consume_code("code123") is None


@pytest.mark.asyncio
async def test_verify_mcp_token_401_cases(client):
    # No header
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert "resource_metadata" in r.headers["WWW-Authenticate"]

    # Invalid token
    r2 = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert r2.status_code == 401
