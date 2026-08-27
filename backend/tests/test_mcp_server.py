"""Tests for StockLens MCP Server (Streamable HTTP + OAuth).

Covers: health, auth gating (401 with WWW-Authenticate + resource_metadata),
initialize/tools/list/tools/call via FastAPI fallback — tests run without
installing the official mcp SDK.

Ponytail: one file, no fixtures bloat — uses existing conftest client + auth_headers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# ── Health (unauthenticated) ───────────────────────────────────────────


async def test_mcp_health_unauthenticated(client: AsyncClient):
    r = await client.get("/mcp/health")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "stocklens-mcp"
    assert data["tools"] == 16
    assert "get_portfolio_summary" in data["tool_names"]


# ── Well-known metadata (unauthenticated) ──────────────────────────────


async def test_well_known_oauth_authorization_server(client: AsyncClient):
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "S256" in data["code_challenge_methods_supported"]


async def test_well_known_protected_resource(client: AsyncClient):
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    data = r.json()
    assert "resource" in data
    assert "authorization_servers" in data


async def test_oauth_register(client: AsyncClient):
    r = await client.post("/oauth/register", json={"redirect_uris": ["http://localhost:6274/callback"]})
    assert r.status_code == 200
    assert r.json()["client_id"] == "stocklens-mcp-public"


# ── Auth gating ────────────────────────────────────────────────────────


async def test_mcp_unauthenticated_returns_401_with_resource_metadata(client: AsyncClient):
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert "resource_metadata" in r.headers["WWW-Authenticate"]
    assert ".well-known/oauth-protected-resource" in r.headers["WWW-Authenticate"]


async def test_mcp_invalid_token_401(client: AsyncClient):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": "Bearer invalid.invalid.invalid"},
    )
    assert r.status_code == 401


# ── Authenticated MCP flow ─────────────────────────────────────────────


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_initialize_and_tools_list(client: AsyncClient, auth_headers: dict[str, str]):
    # initialize
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1.0"}},
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "result" in data
    assert data["result"]["serverInfo"]["name"] == "stocklens"
    assert "tools" in data["result"]["capabilities"]

    # tools/list
    r2 = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=auth_headers,
    )
    assert r2.status_code == 200
    tools = r2.json()["result"]["tools"]
    assert len(tools) == 16
    names = {t["name"] for t in tools}
    assert "get_market_quote" in names
    assert "get_lstm_forecast" in names
    # Injected fields stripped from inputSchema
    for t in tools:
        props = t["inputSchema"].get("properties", {})
        assert "user_id" not in props, f"{t['name']} leaks user_id"
        # portfolio_id is stripped for portfolio tools — verified by adapter
        # market tools never had it anyway


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_tools_call_market_quote(client: AsyncClient, auth_headers: dict[str, str]):
    with patch("src.mcp.tools_adapter.invoke_tool", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = json.dumps({"ticker": "AAPL", "price": 150.0})
        r = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_market_quote", "arguments": {"ticker": "AAPL"}},
            },
            headers=auth_headers,
        )
    assert r.status_code == 200
    data = r.json()
    assert "result" in data
    content = data["result"]["content"]
    assert content[0]["type"] == "text"
    assert "AAPL" in content[0]["text"]


async def test_mcp_tools_call_unknown_tool(client: AsyncClient, auth_headers: dict[str, str]):
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    # JSON-RPC error inside 200
    assert "error" in r.json()
    assert r.json()["error"]["code"] == -32602


# ── OAuth PKCE flow ────────────────────────────────────────────────────
# ponytail: redis loop mismatch in pytest-asyncio (pool created on different loop)
# is fixed by patching _store_code/_consume_code to in-memory dict for this suite.


@pytest.mark.usefixtures("_seed_categories")
async def test_oauth_pkce_authorization_code_flow(client: AsyncClient):
    # Use in-memory code store to avoid redis event-loop cross-talk
    _mem: dict[str, dict] = {}

    async def _fake_store(code: str, data: dict, ttl: int = 600):
        _mem[code] = data

    async def _fake_consume(code: str):
        return _mem.pop(code, None)

    with patch("src.mcp.auth._store_code", side_effect=_fake_store), patch(
        "src.mcp.auth._consume_code", side_effect=_fake_consume
    ):
        # Register user via auth flow to have credentials
        email = f"mcp-oauth-{secrets.token_hex(4)}@stocklens.dev"
        resp = await client.post(
            "/auth/register",
            json={"email": email, "password": "TestPass123!", "full_name": "MCP Tester"},
        )
        assert resp.status_code == 201

        # PKCE: generate verifier + challenge S256
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

        # 1. Authorize — POST with credentials + PKCE
        r1 = await client.post(
            "/oauth/authorize",
            json={
                "email": email,
                "password": "TestPass123!",
                "client_id": "stocklens-mcp-public",
                "redirect_uri": "http://localhost:6274/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "test-state-123",
            },
        )
        assert r1.status_code == 200, r1.text
        code = r1.json()["code"]
        assert r1.json()["state"] == "test-state-123"

        # 2. Token — exchange code + verifier for tokens
        r2 = await client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:6274/callback",
                "client_id": "stocklens-mcp-public",
            },
        )
        assert r2.status_code == 200, r2.text
        tok = r2.json()
        assert "access_token" in tok
        assert tok["token_type"] == "Bearer"
        assert "refresh_token" in tok

        # 3. Use access token on MCP
        r3 = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
            headers={"Authorization": f"Bearer {tok['access_token']}"},
        )
        assert r3.status_code == 200
        assert len(r3.json()["result"]["tools"]) == 16

        # 4. PKCE failure: wrong verifier
        r_bad = await client.post(
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
        bad_code = r_bad.json()["code"]
        r_fail = await client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": bad_code,
                "code_verifier": "wrong-verifier",
                "redirect_uri": "http://localhost:6274/callback",
                "client_id": "stocklens-mcp-public",
            },
        )
        assert r_fail.status_code == 400
        assert "PKCE" in r_fail.json()["detail"]


# ── Additional MCP coverage ──────────────────────────────────────────


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_ping(client: AsyncClient, auth_headers: dict[str, str]):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 10, "method": "ping"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["result"] == {}


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_notifications_initialized_no_response(client: AsyncClient, auth_headers: dict[str, str]):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=auth_headers,
    )
    # Notifications return 202 No Content per JSON-RPC spec
    assert r.status_code == 202


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_unknown_method(client: AsyncClient, auth_headers: dict[str, str]):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 11, "method": "does/not_exist"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32601


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_batch_request(client: AsyncClient, auth_headers: dict[str, str]):
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    r = await client.post("/mcp", json=batch, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_sse_get_requires_auth(client: AsyncClient):
    r = await client.get("/mcp")
    assert r.status_code == 401


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_sse_get_authenticated(client: AsyncClient, auth_headers: dict[str, str]):
    r = await client.get("/mcp", headers=auth_headers)
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: endpoint" in body


async def test_oauth_authorize_get_hint(client: AsyncClient):
    r = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "stocklens-mcp-public",
            "redirect_uri": "http://localhost:6274/callback",
            "code_challenge": "abc123",
            "code_challenge_method": "S256",
            "state": "xyz",
        },
    )
    assert r.status_code == 200
    assert "POST" in r.json()["hint"]["POST"] or "POST" in str(r.json())


@pytest.mark.usefixtures("_seed_categories")
async def test_oauth_token_invalid_code(client: AsyncClient):
    _mem: dict[str, dict] = {}

    async def _fake_consume(code: str):
        return None

    with patch("src.mcp.auth._consume_code", side_effect=_fake_consume):
        r = await client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": "bad-code",
                "code_verifier": "verifier",
                "redirect_uri": "http://localhost:6274/callback",
                "client_id": "stocklens-mcp-public",
            },
        )
        assert r.status_code == 400


@pytest.mark.usefixtures("_seed_categories")
async def test_oauth_token_refresh_flow(client: AsyncClient):
    # Login to get refresh token
    email = f"mcp-refresh-{secrets.token_hex(4)}@stocklens.dev"
    await client.post(
        "/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Refresh Tester"},
    )
    login = await client.post("/auth/login", json={"email": email, "password": "TestPass123!"})
    refresh = login.json()["tokens"]["refresh_token"]

    r = await client.post(
        "/oauth/token",
        json={"grant_type": "refresh_token", "refresh_token": refresh},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()


@pytest.mark.usefixtures("_seed_categories")
async def test_oauth_revoke(client: AsyncClient):
    email = f"mcp-revoke-{secrets.token_hex(4)}@stocklens.dev"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Revoke Tester"},
    )
    token = reg.json()["tokens"]["access_token"]
    r = await client.post("/oauth/revoke", json={"token": token})
    assert r.status_code == 200
    assert r.json()["revoked"] is True

    # Revoked token must now 401 on MCP
    r2 = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/list"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 401

# ── JWKS + Resources/Prompts (enterprise completeness) ────────────────


async def test_jwks_endpoint(client):
    r = await client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    data = r.json()
    assert "keys" in data
    assert len(data["keys"]) == 1
    jwk = data["keys"][0]
    assert jwk["kty"] == "RSA"
    assert jwk["alg"] == "RS256"
    assert jwk["kid"] == "stocklens-mcp-1"
    assert "n" in jwk and "e" in jwk


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_resources_list(client, auth_headers):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 20, "method": "resources/list"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    resources = r.json()["result"]["resources"]
    assert len(resources) == 2
    uris = {res["uri"] for res in resources}
    assert "portfolio://holdings" in uris
    assert "portfolio://summary" in uris


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_resources_read_holdings(client, auth_headers):
    import json
    from unittest.mock import AsyncMock, patch

    with patch("src.mcp.tools_adapter.invoke_tool", new_callable=AsyncMock) as mock:
        mock.return_value = json.dumps({"holdings": [{"ticker": "AAPL", "shares": 10}]})
        r = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 21, "method": "resources/read", "params": {"uri": "portfolio://holdings"}},
            headers=auth_headers,
        )
    assert r.status_code == 200
    contents = r.json()["result"]["contents"]
    assert contents[0]["uri"] == "portfolio://holdings"
    assert "AAPL" in contents[0]["text"]


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_resources_read_unknown(client, auth_headers):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 22, "method": "resources/read", "params": {"uri": "unknown://x"}},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "error" in r.json()


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_prompts_list(client, auth_headers):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 30, "method": "prompts/list"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    prompts = r.json()["result"]["prompts"]
    assert len(prompts) == 1
    assert prompts[0]["name"] == "analyze-portfolio"


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_prompts_get(client, auth_headers):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 31, "method": "prompts/get", "params": {"name": "analyze-portfolio", "arguments": {"focus": "risk"}}},
        headers=auth_headers,
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert "messages" in result
    assert "Analyze portfolio" in result["messages"][0]["content"]["text"]


@pytest.mark.usefixtures("_seed_categories")
async def test_mcp_health_includes_resources_prompts_v2(client):
    r = await client.get("/mcp/health")
    assert r.status_code == 200
    data = r.json()
    assert data["resources"] == 2
    assert data["prompts"] == 1
    assert data["auth"] == "oauth2.1-pkce-rs256"
