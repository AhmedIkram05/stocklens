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
    assert "scope=" in r.headers["WWW-Authenticate"]

    # Invalid token
    r2 = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert r2.status_code == 401
    assert "scope=" in r2.headers["WWW-Authenticate"]


# ── RFC 9207 issuer validation + CIMD (2026-07-28 auth hardening) ──────


def _authorize_body(**overrides):
    body = {
        "email": "test@stocklens.dev",
        "password": "TestPass123!",
        "client_id": "stocklens-mcp-public",
        "redirect_uri": "http://localhost:6274/callback",
        "code_challenge": _code_challenge_s256("v" * 43),
        "code_challenge_method": "S256",
    }
    body.update(overrides)
    return body


def _in_memory_store():
    """Patch _store_code in-memory (existing convention) — avoids a global redis
    client binding to a single test's event loop."""
    mem: dict[str, dict] = {}

    async def _fake_store(code: str, data: dict, ttl: int = 600):
        mem[code] = data

    return patch("src.mcp.auth._store_code", side_effect=_fake_store)


async def test_metadata_advertises_iss_support(client):
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    assert r.json()["authorization_response_iss_parameter_supported"] is True


async def test_authorize_loopback_includes_iss(client, auth_headers):
    with _in_memory_store():
        r = await client.post("/oauth/authorize", json=_authorize_body())
    assert r.status_code == 200, r.text
    assert "iss" in r.json()
    assert r.json()["iss"] == "http://test"  # httpx base_url


async def test_authorize_redirect_includes_iss_param(client, auth_headers):
    with _in_memory_store():
        r = await client.post(
            "/oauth/authorize",
            json=_authorize_body(redirect_uri="https://client.example/cb"),
        )
    assert r.status_code == 302
    assert "iss=" in r.headers["location"]
    assert "http%3A%2F%2Ftest" in r.headers["location"]


async def test_cimd_client_accepted_with_registered_redirect(client, auth_headers):
    doc = {"client_name": "Test Client", "redirect_uris": ["https://client.example/cb"]}
    with patch("src.mcp.auth._fetch_cimd_document", return_value=doc), _in_memory_store():
        r = await client.post(
            "/oauth/authorize",
            json=_authorize_body(
                client_id="https://client.example/cimd.json",
                redirect_uri="https://client.example/cb",
            ),
        )
    # Non-loopback redirect_uri → 302 with code (CIMD validation passed)
    assert r.status_code == 302, r.text
    assert "code=" in r.headers["location"]
    assert "iss=" in r.headers["location"]


async def test_cimd_redirect_uri_not_listed_rejected(client, auth_headers):
    doc = {"client_name": "Test Client", "redirect_uris": ["https://client.example/cb"]}
    with patch("src.mcp.auth._fetch_cimd_document", return_value=doc):
        r = await client.post(
            "/oauth/authorize",
            json=_authorize_body(
                client_id="https://client.example/cimd.json",
                redirect_uri="https://evil.example/cb",
            ),
        )
    assert r.status_code == 400
    assert "redirect_uri" in r.json()["detail"]


async def test_cimd_unreachable_document_rejected(client, auth_headers):
    with patch("src.mcp.auth._fetch_cimd_document", return_value=None):
        r = await client.post(
            "/oauth/authorize",
            json=_authorize_body(
                client_id="https://client.example/cimd.json",
                redirect_uri="https://client.example/cb",
            ),
        )
    assert r.status_code == 400


def test_cimd_host_blocked_literals():
    from src.mcp.auth import _cimd_host_blocked

    # Literal IPs never need DNS
    assert _cimd_host_blocked("localhost") is True
    assert _cimd_host_blocked("127.0.0.1") is True
    assert _cimd_host_blocked("10.0.0.5") is True
    assert _cimd_host_blocked("192.168.1.1") is True
    assert _cimd_host_blocked("169.254.169.254") is True


def test_cimd_host_blocked_hostname():
    from src.mcp.auth import _cimd_host_blocked

    with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("93.184.216.34", 443))]):
        assert _cimd_host_blocked("client.example") is False
    with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("10.0.0.5", 443))]):
        assert _cimd_host_blocked("client.example") is True
    with patch("socket.getaddrinfo", side_effect=OSError("no dns")):
        assert _cimd_host_blocked("client.example") is True


def test_cimd_host_blocked_local_suffix():
    from src.mcp.auth import _cimd_host_blocked

    assert _cimd_host_blocked("myclient.local") is True


def test_is_cimd_client_id():
    from src.mcp.auth import _is_cimd_client_id

    assert _is_cimd_client_id("https://client.example/cimd.json") is True
    assert _is_cimd_client_id("http://client.example/cimd.json") is False
    assert _is_cimd_client_id("stocklens-mcp-public") is False


class _FakeUrlopenResp:
    """Minimal context manager mimicking urllib.response.addinfourl for _fetch_cimd_document."""

    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._raw


def _fetch_with_mock(raw: bytes | None = None, exc: Exception | None = None, client_id: str = "https://client.example/cimd.json"):
    # Clear module cache so TTL state doesn't leak between tests
    import src.mcp.auth as mcp_auth

    mcp_auth._CIMD_CACHE.clear()
    if exc is not None:
        return patch("urllib.request.urlopen", side_effect=exc)
    return patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(raw or b""))


def test_fetch_cimd_document_success_and_cached():
    import json as _json

    import src.mcp.auth as mcp_auth

    payload = _FakeUrlopenResp(
        _json.dumps({"client_name": "C", "redirect_uris": ["https://c.example/cb"]}).encode()
    )
    mcp_auth._CIMD_CACHE.clear()
    # client.example has no DNS record — pin getaddrinfo to a public IP for the SSRF check
    with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("93.184.216.34", 443))]), \
         patch("urllib.request.urlopen", return_value=payload) as urlopen:
        doc = mcp_auth._fetch_cimd_document("https://client.example/cimd.json")
        assert doc == {"client_name": "C", "redirect_uris": ["https://c.example/cb"]}
        # second call served from cache — urlopen only used once
        assert mcp_auth._fetch_cimd_document("https://client.example/cimd.json") == doc
    assert urlopen.call_count == 1


def test_fetch_cimd_document_invalid_json_returns_none():
    import src.mcp.auth as mcp_auth

    with _fetch_with_mock(raw=b"not json"):
        assert mcp_auth._fetch_cimd_document("https://client.example/cimd.json") is None


def test_fetch_cimd_document_non_dict_returns_none():
    import src.mcp.auth as mcp_auth

    with _fetch_with_mock(raw=b"[1, 2, 3]"):
        assert mcp_auth._fetch_cimd_document("https://client.example/cimd.json") is None


def test_fetch_cimd_document_missing_redirect_uris_returns_none():
    import json as _json

    import src.mcp.auth as mcp_auth

    with _fetch_with_mock(raw=_json.dumps({"client_name": "C"}).encode()):
        assert mcp_auth._fetch_cimd_document("https://client.example/cimd.json") is None
    with _fetch_with_mock(raw=_json.dumps({"redirect_uris": "not-a-list"}).encode()):
        assert mcp_auth._fetch_cimd_document("https://client.example/cimd.json") is None


def test_fetch_cimd_document_blocked_host_returns_none():
    import src.mcp.auth as mcp_auth

    # localhost → SSRF block before any network call
    with _fetch_with_mock(exc=AssertionError("urlopen must not be called")):
        assert mcp_auth._fetch_cimd_document("https://localhost/cimd.json") is None


def test_fetch_cimd_document_urlopen_error_returns_none():
    import src.mcp.auth as mcp_auth

    with _fetch_with_mock(exc=OSError("connection refused")):
        assert mcp_auth._fetch_cimd_document("https://client.example/cimd.json") is None


async def test_cimd_client_name_stored_on_authorize(client, auth_headers):
    stored: dict[str, dict] = {}

    async def capture_store(code: str, data: dict, ttl: int = 600):
        stored[code] = data

    doc = {"client_name": "Acme Tool", "redirect_uris": ["https://client.example/cb"]}
    with (
        patch("src.mcp.auth._fetch_cimd_document", return_value=doc),
        patch("src.mcp.auth._store_code", side_effect=capture_store),
    ):
        r = await client.post(
            "/oauth/authorize",
            json=_authorize_body(
                client_id="https://client.example/cimd.json",
                redirect_uri="https://client.example/cb",
            ),
        )
    assert r.status_code == 302
    payload = next(iter(stored.values()))
    assert payload["client_name"] == "Acme Tool"


async def test_default_client_name_stored_without_cimd(client, auth_headers):
    stored: dict[str, dict] = {}

    async def capture_store(code: str, data: dict, ttl: int = 600):
        stored[code] = data

    with patch("src.mcp.auth._store_code", side_effect=capture_store):
        await client.post("/oauth/authorize", json=_authorize_body())
    payload = next(iter(stored.values()))
    assert payload["client_name"] == "StockLens MCP"
