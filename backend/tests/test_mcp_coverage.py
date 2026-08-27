"""Extra coverage for MCP — hit the 76%→88% gap.

Covers: RSA PEM path, RS256 encode/dual decode, PKCE plain, missing
code_challenge, redirect_uri mismatch, unsupported grant, revoke no token,
verify 403/404, resources/prompts error paths, batch mixed, SSE accept,
adapter edge cases.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
import jwt as pyjwt


# ── auth.py: RSA/JWKS & token helpers ──────────────────────────────────


def test_get_rsa_keypair_ephemeral_and_cached():
    # Ephemeral generation + caching — no env PEM needed (covers _get_rsa_keypair path)
    import src.mcp.auth as mcp_auth
    from src.mcp.auth import _get_rsa_keypair

    mcp_auth._RSA_KEYPAIR = None
    pair1 = _get_rsa_keypair()
    pair2 = _get_rsa_keypair()
    assert pair1 is not None
    assert pair1 is pair2  # cached
    mcp_auth._RSA_KEYPAIR = None  # cleanup for other tests
    assert _get_rsa_keypair() is not None


def test_try_rs256_encode_and_jwks():
    from src.mcp.auth import _try_rs256_encode, _jwks, _public_jwk, _private_pem, _public_pem

    # Should succeed with ephemeral key
    tok = _try_rs256_encode({"sub": "u1", "exp": 9999999999})
    assert tok is not None
    assert tok.count(".") == 2
    # Header should be RS256 with kid
    hdr = pyjwt.get_unverified_header(tok)
    assert hdr["alg"] == "RS256"
    assert hdr["kid"] == "stocklens-mcp-1"

    jwks = _jwks()
    assert "keys" in jwks and len(jwks["keys"]) == 1
    assert jwks["keys"][0]["kty"] == "RSA"
    assert _public_jwk() is not None
    assert _private_pem() is not None
    assert _public_pem() is not None


def test_mcp_create_access_token_rs256_header():
    from src.mcp.auth import _mcp_create_access_token, _decode_mcp_token

    tok, jti, exp = _mcp_create_access_token("user-123")
    hdr = pyjwt.get_unverified_header(tok)
    assert hdr["alg"] in ("RS256", "HS256")
    if hdr["alg"] == "RS256":
        assert hdr["kid"] == "stocklens-mcp-1"
        payload = _decode_mcp_token(tok)
        assert payload.sub == "user-123"
        assert payload.type == "access"


def test_decode_mcp_token_dual_fallback():
    from src.auth.utils import create_access_token
    from src.mcp.auth import _decode_mcp_token

    # HS256 token via legacy helper must still decode via dual decoder
    tok, _ = create_access_token("user-hs256")
    payload = _decode_mcp_token(tok)
    assert payload.sub == "user-hs256"


@pytest.mark.asyncio
async def test_oauth_authorize_missing_challenge(client: AsyncClient):
    r = await client.post(
        "/oauth/authorize",
        json={
            "email": "test@example.com",
            "password": "x",
            "client_id": "c",
            "redirect_uri": "http://localhost:6274/callback",
            "code_challenge": "",  # missing
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400
    assert "code_challenge" in r.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_authorize_plain_pkce(client: AsyncClient):
    # Register user first
    email = f"mcp-plain-{secrets.token_hex(4)}@stocklens.dev"
    await client.post("/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Plain"})
    verifier = "plain-verifier-123"
    # plain == verifier == challenge
    r = await client.post(
        "/oauth/authorize",
        json={
            "email": email,
            "password": "TestPass123!",
            "client_id": "stocklens-mcp-public",
            "redirect_uri": "http://localhost:6274/callback",
            "code_challenge": verifier,
            "code_challenge_method": "plain",
            "state": "s1",
        },
    )
    assert r.status_code == 200
    code = r.json()["code"]
    # Token with plain verifier should succeed when patched to avoid redis loop
    _mem: dict[str, dict] = {}

    async def _fake_store(c, d, ttl=600):
        _mem[c] = d

    async def _fake_consume(c):
        return _mem.pop(c, None)

    with patch("src.mcp.auth._store_code", side_effect=_fake_store), patch(
        "src.mcp.auth._consume_code", side_effect=_fake_consume
    ):
        # Need to redo authorize with patched store to have code in _mem
        r2 = await client.post(
            "/oauth/authorize",
            json={
                "email": email,
                "password": "TestPass123!",
                "client_id": "stocklens-mcp-public",
                "redirect_uri": "http://localhost:6274/callback",
                "code_challenge": verifier,
                "code_challenge_method": "plain",
            },
        )
        code2 = r2.json()["code"]
        r3 = await client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code2,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:6274/callback",
                "client_id": "stocklens-mcp-public",
            },
        )
        assert r3.status_code == 200


@pytest.mark.asyncio
async def test_oauth_token_redirect_mismatch(client: AsyncClient):
    _mem: dict[str, dict] = {}

    async def _fake_store(c, d, ttl=600):
        _mem[c] = d

    async def _fake_consume(c):
        return _mem.pop(c, None)

    email = f"mcp-mismatch-{secrets.token_hex(4)}@stocklens.dev"
    await client.post("/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Mismatch"})

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    with patch("src.mcp.auth._store_code", side_effect=_fake_store), patch(
        "src.mcp.auth._consume_code", side_effect=_fake_consume
    ):
        r1 = await client.post(
            "/oauth/authorize",
            json={
                "email": email,
                "password": "TestPass123!",
                "client_id": "stocklens-mcp-public",
                "redirect_uri": "http://localhost:6274/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        code = r1.json()["code"]
        r2 = await client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:6275/other",  # mismatch
                "client_id": "stocklens-mcp-public",
            },
        )
        assert r2.status_code == 400
        assert "redirect_uri" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_token_unsupported_grant(client: AsyncClient):
    r = await client.post("/oauth/token", json={"grant_type": "client_credentials"})
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_revoke_no_token(client: AsyncClient):
    r = await client.post("/oauth/revoke", json={})
    assert r.status_code == 200
    assert r.json()["revoked"] is False

    r2 = await client.post("/oauth/revoke", json={"token": "not.a.jwt"})
    assert r2.json()["revoked"] is False

    # refresh hint path
    r3 = await client.post("/oauth/revoke", json={"token": "not.a.jwt", "token_type_hint": "refresh_token"})
    assert r3.json()["revoked"] is False


@pytest.mark.asyncio
async def test_verify_mcp_token_user_not_found_or_inactive(client: AsyncClient, auth_headers: dict[str, str]):
    # Use valid token but mock DB to return None / inactive
    tok = auth_headers["Authorization"].split()[1]

    with patch("src.mcp.auth.connection_ctx") as mock_ctx:
        # Not found
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=auth_headers)
        # Should be 401 user not found
        assert r.status_code == 401

    with patch("src.mcp.auth.connection_ctx") as mock_ctx2:
        mock_conn2 = AsyncMock()
        mock_conn2.fetchrow = AsyncMock(return_value={"id": "x", "is_active": False})
        mock_ctx2.return_value.__aenter__ = AsyncMock(return_value=mock_conn2)
        mock_ctx2.return_value.__aexit__ = AsyncMock(return_value=None)
        r2 = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=auth_headers)
        assert r2.status_code == 403


@pytest.mark.asyncio
async def test_mcp_batch_mixed_ok_error(client: AsyncClient, auth_headers: dict[str, str]):
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "does/not_exist"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no response
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_market_quote", "arguments": {"ticker": "AAPL"}}},
    ]
    with patch("src.mcp.tools_adapter.invoke_tool", new_callable=AsyncMock) as mock:
        mock.return_value = json.dumps({"price": 1})
        r = await client.post("/mcp", json=batch, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # 4 responses (notifications has no response)
    assert len(data) == 4
    methods = {x.get("id"): x for x in data}
    assert "result" in methods[1]  # ping
    assert "result" in methods[2]  # tools/list
    assert "error" in methods[3]  # unknown


@pytest.mark.asyncio
async def test_mcp_sse_accept_header(client: AsyncClient, auth_headers: dict[str, str]):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 99, "method": "ping"},
        headers={**auth_headers, "Accept": "text/event-stream"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: message" in r.text


@pytest.mark.asyncio
async def test_mcp_tools_call_exception_path(client: AsyncClient, auth_headers: dict[str, str]):
    with patch("src.mcp.tools_adapter.invoke_tool", new_callable=AsyncMock) as mock:
        mock.side_effect = KeyError("Unknown tool: nope")
        r = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            headers=auth_headers,
        )
        # Our server maps KeyError to -32602 inside tools/call path, but direct side_effect
        # goes to outer KeyError handler -> -32602
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32602


def test_strip_injected_empty_and_no_required():
    from src.mcp.tools_adapter import _strip_injected

    assert _strip_injected({}) == {}
    assert _strip_injected({"properties": {"a": {"type": "string"}}})["properties"] == {"a": {"type": "string"}}
    out = _strip_injected({"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]})
    assert out["required"] == ["ticker"]


def test_get_mcp_tools_fallback_via_get_input_schema():
    from unittest.mock import MagicMock, patch

    mock_tool = MagicMock()
    mock_tool.name = "fallback_tool"
    mock_tool.description = "fallback"
    mock_tool.args_schema = None
    mock_tool.args = {}
    # get_input_schema returns a pydantic model with portfolio_id
    schema_mock = MagicMock()
    schema_mock.model_json_schema.return_value = {
        "type": "object",
        "properties": {"user_id": {"type": "string"}, "portfolio_id": {"type": "string"}, "ticker": {"type": "string"}},
        "required": ["ticker", "user_id"],
    }
    mock_tool.get_input_schema = MagicMock(return_value=schema_mock)

    with patch("src.mcp.tools_adapter._load_tools", return_value={"fallback_tool": mock_tool}):
        from src.mcp.tools_adapter import get_mcp_tools

        defs = get_mcp_tools()
        assert any(d["name"] == "fallback_tool" for d in defs)
        fd = [d for d in defs if d["name"] == "fallback_tool"][0]
        assert "user_id" not in fd["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_resolve_portfolio_db_error():
    from unittest.mock import patch
    from src.mcp.tools_adapter import resolve_portfolio_id

    with patch("src.database.connection.connection_ctx", side_effect=Exception("db down")):
        pid = await resolve_portfolio_id("user-1")
        assert pid == ""


@pytest.mark.asyncio
async def test_invoke_tool_non_string_result():
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.mcp.tools_adapter import invoke_tool

    mock_tool = MagicMock()
    mock_tool.name = "get_market_quote"
    mock_tool.args_schema = None
    mock_tool.args = {"properties": {"ticker": {"type": "string"}}, "type": "object"}
    mock_tool.get_input_schema = MagicMock(side_effect=Exception("no schema"))
    # Return dict, not string — adapter must json.dumps
    mock_tool.ainvoke = AsyncMock(return_value={"price": 123})

    with patch("src.mcp.tools_adapter._load_tools", return_value={"get_market_quote": mock_tool}):
        result = await invoke_tool("get_market_quote", {"ticker": "AAPL"}, user_id="u1")
        assert json.loads(result)["price"] == 123
