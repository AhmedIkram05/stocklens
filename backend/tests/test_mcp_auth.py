"""Tests for MCP OAuth helpers — PKCE, token helpers, verifier.

Ponytail: no redis mock bloat — tests hit pure functions or patch redis.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

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
            json=_authorize_body(redirect_uri="https://claude.ai/callback"),
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


def _fetch_with_mock(
    raw: bytes | None = None,
    exc: Exception | None = None,
    client_id: str = "https://client.example/cimd.json",
):
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
    with (
        patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("93.184.216.34", 443))]),
        patch("urllib.request.urlopen", return_value=payload) as urlopen,
    ):
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


# ── First-party redirect_uri allowlist + strict token exchange ─────────


def _fake_oauth_request():
    return type("R", (), {"base_url": "http://localhost:8000/"})()


def test_first_party_redirect_allowlist():
    from src.mcp.auth import _is_first_party_redirect

    # RFC 8252 §7.3 loopback — any port, IPv4 / IPv6 / localhost
    assert _is_first_party_redirect("http://127.0.0.1:6274/callback") is True
    assert _is_first_party_redirect("http://localhost:6274/callback") is True
    assert _is_first_party_redirect("http://[::1]:9000/callback") is True
    assert _is_first_party_redirect("http://127.0.0.1") is True
    # Registered default host from POST /oauth/register
    assert _is_first_party_redirect("https://claude.ai/callback") is True
    # Hostile / unregistered
    assert _is_first_party_redirect("https://evil.example/cb") is False
    # userinfo tricks never mask the real host (WHATWG: host = after last '@')
    assert _is_first_party_redirect("http://127.0.0.1@evil.example/cb") is False
    assert _is_first_party_redirect("https://claude.ai.evil.example/cb") is False
    assert _is_first_party_redirect("http://127.0.0.1.evil.example/cb") is False
    # Unparsable
    assert _is_first_party_redirect("not a uri") is False
    assert _is_first_party_redirect("http://[::1/cb") is False


async def test_authorize_public_client_rejects_hostile_redirect_uri():
    from fastapi import HTTPException

    from src.mcp.auth import AuthorizeRequest, oauth_authorize_post

    body = AuthorizeRequest(**_authorize_body(redirect_uri="https://evil.example/cb"))
    with (
        patch(
            "src.mcp.auth._authenticate_user",
            new_callable=AsyncMock,
            return_value={"id": "u1"},
        ),
        patch("src.mcp.auth._store_code", new_callable=AsyncMock) as store,
    ):
        with pytest.raises(HTTPException) as exc:
            await oauth_authorize_post(body, _fake_oauth_request())
    assert exc.value.status_code == 400
    assert "redirect_uri" in exc.value.detail
    store.assert_not_called()  # no code is ever minted for a hostile redirect


async def test_authorize_non_https_client_id_rejects_hostile_redirect_uri():
    from fastapi import HTTPException

    from src.mcp.auth import AuthorizeRequest, oauth_authorize_post

    body = AuthorizeRequest(
        **_authorize_body(client_id="custom-native-client", redirect_uri="https://evil.example/cb")
    )
    with (
        patch(
            "src.mcp.auth._authenticate_user",
            new_callable=AsyncMock,
            return_value={"id": "u1"},
        ),
        patch("src.mcp.auth._store_code", new_callable=AsyncMock),
    ):
        with pytest.raises(HTTPException) as exc:
            await oauth_authorize_post(body, _fake_oauth_request())
    assert exc.value.status_code == 400


async def test_authorize_public_client_accepts_loopback_any_port():
    from fastapi.responses import RedirectResponse

    from src.mcp.auth import AuthorizeRequest, oauth_authorize_post

    with (
        patch(
            "src.mcp.auth._authenticate_user",
            new_callable=AsyncMock,
            return_value={"id": "u1"},
        ),
        patch("src.mcp.auth._store_code", new_callable=AsyncMock),
    ):
        # IPv4 loopback / localhost → JSON code response (existing behaviour)
        body = AuthorizeRequest(**_authorize_body(redirect_uri="http://127.0.0.1:8765/cb"))
        r = await oauth_authorize_post(body, _fake_oauth_request())
        assert r["code"]
        assert r["iss"] == "http://localhost:8000"

        # IPv6 loopback → 302 carrying the code (presentation branch is
        # IPv4-prefix based; the security allowlist accepts [::1] too)
        body6 = AuthorizeRequest(**_authorize_body(redirect_uri="http://[::1]:9000/cb"))
        r6 = await oauth_authorize_post(body6, _fake_oauth_request())
        assert isinstance(r6, RedirectResponse)
        assert r6.status_code == 302
        assert "code=" in r6.headers["location"]


async def test_authorize_public_client_accepts_registered_https_redirect():
    from fastapi.responses import RedirectResponse

    from src.mcp.auth import AuthorizeRequest, oauth_authorize_post

    body = AuthorizeRequest(**_authorize_body(redirect_uri="https://claude.ai/callback"))
    with (
        patch(
            "src.mcp.auth._authenticate_user",
            new_callable=AsyncMock,
            return_value={"id": "u1"},
        ),
        patch("src.mcp.auth._store_code", new_callable=AsyncMock),
    ):
        r = await oauth_authorize_post(body, _fake_oauth_request())
    assert isinstance(r, RedirectResponse)
    assert r.status_code == 302
    assert "code=" in r.headers["location"]


class _FakeTokenRequest:
    """Minimal Request stand-in for oauth_token (JSON content-type)."""

    def __init__(self, data: dict):
        self.headers = {"content-type": "application/json"}
        self._data = data

    async def json(self):
        return self._data


def _stored_code_data() -> dict:
    return {
        "user_id": "u1",
        "client_id": "stocklens-mcp-public",
        "client_name": "StockLens MCP",
        "redirect_uri": "http://localhost:6274/callback",
        "code_challenge": _code_challenge_s256("v" * 43),
        "code_challenge_method": "S256",
        "scope": "mcp:tools",
        "created_at": 0,
    }


def _exchange_conn_ctx_mock():
    """connection_ctx stand-in for the refresh-token INSERT at exchange."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
    ctx = MagicMock()
    ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.return_value.__aexit__ = AsyncMock(return_value=None)
    return ctx


async def _run_token_exchange(data: dict, stored: dict):
    from src.mcp.auth import oauth_token

    with (
        patch("src.mcp.auth._consume_code", new_callable=AsyncMock, return_value=stored),
        patch("src.mcp.auth.connection_ctx", _exchange_conn_ctx_mock()),
    ):
        return await oauth_token(_FakeTokenRequest(data))


async def test_token_exchange_missing_redirect_uri_rejected():
    from fastapi import HTTPException

    data = {
        "grant_type": "authorization_code",
        "code": "c1",
        "code_verifier": "v" * 43,
        "client_id": "stocklens-mcp-public",
    }
    with pytest.raises(HTTPException) as exc:
        await _run_token_exchange(data, _stored_code_data())
    assert exc.value.status_code == 400
    assert "redirect_uri" in exc.value.detail


async def test_token_exchange_mismatched_redirect_uri_rejected():
    from fastapi import HTTPException

    data = {
        "grant_type": "authorization_code",
        "code": "c1",
        "code_verifier": "v" * 43,
        "redirect_uri": "http://localhost:9999/other",
        "client_id": "stocklens-mcp-public",
    }
    with pytest.raises(HTTPException) as exc:
        await _run_token_exchange(data, _stored_code_data())
    assert exc.value.status_code == 400
    assert "redirect_uri" in exc.value.detail


async def test_token_exchange_mismatched_client_id_rejected():
    from fastapi import HTTPException

    data = {
        "grant_type": "authorization_code",
        "code": "c1",
        "code_verifier": "v" * 43,
        "redirect_uri": "http://localhost:6274/callback",
        "client_id": "other-client",
    }
    with pytest.raises(HTTPException) as exc:
        await _run_token_exchange(data, _stored_code_data())
    assert exc.value.status_code == 400
    assert "client_id" in exc.value.detail


async def test_token_exchange_matching_params_issues_tokens():
    data = {
        "grant_type": "authorization_code",
        "code": "c1",
        "code_verifier": "v" * 43,
        "redirect_uri": "http://localhost:6274/callback",
        "client_id": "stocklens-mcp-public",
    }
    result = await _run_token_exchange(data, _stored_code_data())
    assert "access_token" in result
    assert "refresh_token" in result
    assert result["token_type"] == "Bearer"


# ── Refresh rotation: atomic single-use claim ───────────────────────────


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
                return None  # rowcount 0 → reuse path
            self.tokens[token_hash] = True
            return True  # rowcount 1 → mint path
        raise AssertionError(f"unexpected fetchval: {query[:60]}")

    async def fetchrow(self, query, *args):
        if "SELECT revoked FROM refresh_tokens" in query:
            (token_hash,) = args
            if token_hash not in self.tokens:
                return None
            return {"revoked": self.tokens[token_hash]}
        raise AssertionError(f"unexpected fetchrow: {query[:60]}")

    async def execute(self, query, *args):
        if "UPDATE refresh_tokens SET revoked = true WHERE user_id" in query:
            self.revoked_all_for.append(args[0])
            return "UPDATE 0"
        if "INSERT INTO refresh_tokens" in query:
            self.new_inserts.append(args)
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {query[:60]}")


class _FakeRefreshCtx:
    def __init__(self, conn):
        self._conn = conn

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


async def _call_refresh(conn, jti="jti-race", user="user-race"):
    from src.auth.schemas import TokenPayload
    from src.mcp.auth import oauth_token

    payload = TokenPayload(sub=user, jti=jti, exp=2_000_000_000, iat=1_000_000_000, type="refresh")
    request = _FakeTokenRequest({"grant_type": "refresh_token", "refresh_token": "rt"})
    with (
        patch("src.mcp.auth.connection_ctx", _FakeRefreshCtx(conn)),
        patch("src.mcp.auth.is_token_blacklisted", new_callable=AsyncMock, return_value=False),
        patch("src.cache.redis.blacklist_token", new_callable=AsyncMock),
        patch("src.mcp.auth._decode_mcp_token", return_value=payload),
    ):
        return await oauth_token(request)


async def test_double_refresh_same_jti_second_takes_reuse_path():
    import asyncio

    from fastapi import HTTPException

    from src.auth.utils import hash_token

    conn = _FakeRefreshConn()
    token_hash = hash_token("jti-race", "user-race")
    conn.seed(token_hash)

    results = await asyncio.gather(
        _call_refresh(conn),
        _call_refresh(conn),
        return_exceptions=True,
    )

    http_errors = [r for r in results if isinstance(r, HTTPException)]
    successes = [r for r in results if isinstance(r, dict)]
    assert len(successes) == 1, "only one refresh may mint a new pair"
    assert len(http_errors) == 1
    # The loser takes the stolen-token reuse path, not a plain not-found.
    assert http_errors[0].status_code == 401
    assert "re-login required" in http_errors[0].detail
    assert conn.revoked_all_for == ["user-race"]
    # Exactly one new refresh token was minted across both requests.
    assert len(conn.new_inserts) == 1
    # The claim is a single conditional UPDATE (no check-then-act SELECT first).
    assert conn.claim_queries
    for q in conn.claim_queries:
        assert "AND revoked = false" in q


# ── RS256 configured-key path (JWT_PRIVATE_KEY) ────────────────────────────────

_RSA_TEST_PEM: str | None = None


def _test_rsa_pem() -> str:
    """Generate a test RSA PEM once per session (keygen is ~100ms)."""
    global _RSA_TEST_PEM
    if _RSA_TEST_PEM is None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

        key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
        _RSA_TEST_PEM = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    return _RSA_TEST_PEM


@pytest.fixture
def fresh_keypair():
    """Reset the cached RSA keypair state; restore whatever was cached."""
    from src.mcp import auth as auth_mod

    old_pair, old_kid = auth_mod._RSA_KEYPAIR, auth_mod._CONFIGURED_KID
    auth_mod._RSA_KEYPAIR = None
    auth_mod._CONFIGURED_KID = None
    yield
    auth_mod._RSA_KEYPAIR, auth_mod._CONFIGURED_KID = old_pair, old_kid


@pytest.fixture
def structlog_caplog():
    """Route structlog through stdlib logging so caplog can capture events."""
    import structlog

    saved = structlog.get_config()
    structlog.configure(logger_factory=structlog.stdlib.LoggerFactory())
    yield
    structlog.configure(**saved)


class TestRS256ConfiguredKey:
    """JWT_PRIVATE_KEY path — persistent key, stable kid, loud fallback."""

    def test_configured_pem_produces_stable_jwks_across_instantiations(
        self, fresh_keypair, monkeypatch
    ):
        from src.config import settings
        from src.mcp import auth as auth_mod

        pem = _test_rsa_pem()
        monkeypatch.setattr(settings, "JWT_PRIVATE_KEY", pem)

        auth_mod._get_rsa_keypair()
        jwks1 = auth_mod._jwks()

        # Simulate a second process: fresh keypair state, same configured key
        auth_mod._RSA_KEYPAIR = None
        auth_mod._CONFIGURED_KID = None
        jwks2 = auth_mod._jwks()

        assert jwks1["keys"] == jwks2["keys"], "configured key must not rotate per process"

        # kid is the fingerprint of the configured public key, not the legacy kid
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(pem.encode(), password=None)
        der = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.PKCS1
        )
        expected_kid = hashlib.sha256(der).hexdigest()[:16]
        assert jwks1["keys"][0]["kid"] == expected_kid
        assert jwks1["keys"][0]["kid"] != "stocklens-mcp-1"

    def test_ephemeral_fallback_warns_when_unconfigured(
        self, fresh_keypair, monkeypatch, structlog_caplog, caplog
    ):
        import logging

        from src.config import settings
        from src.mcp import auth as auth_mod

        monkeypatch.setattr(settings, "JWT_PRIVATE_KEY", "")
        with caplog.at_level(logging.WARNING):
            pair = auth_mod._get_rsa_keypair()

        assert pair is not None  # ephemeral path still works
        assert any(
            "jwt_private_key_not_configured_ephemeral_keys_in_use" in r.getMessage()
            for r in caplog.records
        )

    def test_invalid_pem_falls_back_loudly(
        self, fresh_keypair, monkeypatch, structlog_caplog, caplog
    ):
        import logging

        from src.config import settings
        from src.mcp import auth as auth_mod

        monkeypatch.setattr(settings, "JWT_PRIVATE_KEY", "not-a-pem")
        with caplog.at_level(logging.ERROR):
            pair = auth_mod._get_rsa_keypair()

        assert pair is not None  # degraded to ephemeral, not dead
        assert any(
            "jwt_private_key_unusable_falling_back_to_ephemeral" in r.getMessage()
            for r in caplog.records
        )

    def test_sign_verify_roundtrip_with_configured_key(self, fresh_keypair, monkeypatch):
        from src.config import settings
        from src.mcp.auth import _decode_mcp_token, _mcp_create_access_token

        monkeypatch.setattr(settings, "JWT_PRIVATE_KEY", _test_rsa_pem())

        tok, _jti, _exp = _mcp_create_access_token("user-123")
        payload = _decode_mcp_token(tok)
        assert payload.sub == "user-123"
        assert payload.type == "access"
