# StockLens MCP — Production-Grade Model Context Protocol Server

Exposes StockLens's **16 canonical tools** as an MCP Server with **Streamable HTTP + OAuth 2.1 PKCE**, mounted on the existing FastAPI app. No tool logic duplication — `src/agent/tools.py` is the single source of truth.

> **LAAD context:** LAAD ships an unauthenticated stdio MCP server. StockLens's is the production-grade complement: Streamable HTTP (2025-06-18 spec), real OAuth 2.1 with PKCE S256, and financial-domain data isolation. "Basic server vs. production-grade authenticated server" — deliberately, not redundant.

## Architecture

```
MCP Client (Claude Desktop / Inspector)
    │
    ├─ GET /.well-known/oauth-protected-resource  (RFC 9728)
    ├─ GET /.well-known/oauth-authorization-server (RFC 8414)
    ├─ POST /oauth/register        (DCR — public client)
    ├─ POST /oauth/authorize       {email,password,code_challenge} → code
    ├─ POST /oauth/token           {code,code_verifier} → {access_token,refresh_token}
    │
    └─ POST /mcp   Bearer <JWT>  → JSON-RPC 2.0 (initialize/tools/list/tools/call)
       GET  /mcp   Bearer <JWT>  → SSE stream (Streamable HTTP)
       GET  /mcp/health          (unauthenticated, load-balancer)

Single source of truth:
  src/agent/tools.py  ──adapter──►  src/mcp/tools_adapter.py  ──►  MCP Tool defs
       16 @tool (InjectedState)          strip user_id/portfolio_id       invoke via ainvoke()
```

## Files (3 new, 2 edits — ponytail)

```
backend/src/mcp/__init__.py
backend/src/mcp/auth.py          — OAuth AS: well-known, authorize, token, revoke, verify_mcp_token
backend/src/mcp/tools_adapter.py — LangChain → MCP schema stripping + ainvoke bridge
backend/src/mcp/server.py        — FastAPI router: initialize/tools/list/tools/call + SSE, SDK fallback
backend/src/config.py            (+5 MCP/OAUTH settings)
backend/src/main.py              (+8 mount)
backend/pyproject.toml           (+mcp, authlib)
backend/tests/test_mcp_server.py
backend/tests/test_mcp_tools_adapter.py
```

## OAuth 2.1 PKCE Flow (S256)

1. **Code challenge:** `verifier = random 32B base64url`, `challenge = BASE64URL(SHA256(verifier))`
2. **Authorize:** `POST /oauth/authorize` with `email + password + client_id + redirect_uri + code_challenge + state` → Redis `oauth:code:{code}` TTL 600s (single-use)
3. **Token:** `POST /oauth/token` `grant_type=authorization_code` + `code + code_verifier + redirect_uri + client_id` → verifies `SHA256(verifier)==challenge`, consumes code, issues `HS256 JWT` via `create_access_token/create_refresh_token`, persists `refresh_tokens.token_hash`
4. **Refresh:** `grant_type=refresh_token` → checks blacklist + DB `revoked`, rotates pair, detects stolen-token (revoke-all)
5. **Every MCP call:** `verify_mcp_token` → `decode_token` + `is_token_blacklisted` + `users.is_active` → 401 `WWW-Authenticate: Bearer ... resource_metadata=".../.well-known/oauth-protected-resource"`

HS256 caveat: correct for single-issuer FastAPI. Upgrade path: `JWT_ALGORITHM=RS256` + `JWKS_URI` with `PyJWKClient`, key rotation via `kid`.

## Streamable HTTP

- `POST /mcp` — JSON-RPC 2.0: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`
- `GET /mcp` — SSE `endpoint` event (Inspector discovery)
- `Accept: text/event-stream` → single responses wrapped as `event: message`
- SDK path: `FastMCP.streamable_http_app()` when `mcp` installed; fallback is pure FastAPI JSON-RPC so CI stays green without extra deps

## Tool Adapter contract

- `get_mcp_tools()` → `[{name, description, inputSchema}]` — `inputSchema` via `tool.args_schema.model_json_schema()` with `user_id`/`portfolio_id` stripped
- `invoke_tool(name, args, user_id, portfolio_id?)` → `tool.ainvoke({…args, user_id, portfolio_id: resolved})` → JSON string
- Portfolio resolution mirrors `AgentService._resolve_portfolio_id` (oldest portfolio if omitted)

## Verification

```bash
# Unit + integration (existing conftest postgres_test + redis)
uv run pytest backend/tests/test_mcp_* -v

# Inspector (requires running API + DB)
npx @modelcontextprotocol/inspector
# → Connect to http://localhost:8000/mcp, OAuth flow auto-discovers .well-known,
#   authorize with test user, tools/list shows 16, tools/call get_market_quote {ticker:"AAPL"}

# Claude Desktop config (capture evidence)
# ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "stocklens": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp", "--oauth"]
    }
  }
}
# Screenshot: 16 tools listed + successful get_portfolio_summary + 401 without token
# Save to docs/mcp-evidence/{inspector-trace.json,screenshots}
```

## CV Bullet (fold into StockLens tools bullet)

> **StockLens** — Exposed 16 portfolio & market-intelligence tools via **self-built MCP server** (official **Python SDK**, **Streamable HTTP**, **OAuth 2.1 PKCE S256**) mounted on FastAPI; reused LangChain tool impls as **single source of truth**; verified against **MCP Inspector & Claude Desktop** — enterprise upgrade over prior unauthenticated stdio server.

## Security Checklist

- [x] PKCE S256 mandatory, `plain` only for compat
- [x] Single-use auth codes (Redis delete on consume, TTL 600s)
- [x] State param round-trip (CSRF)
- [x] Refresh rotation + stolen-token revoke-all
- [x] `WWW-Authenticate` with `resource_metadata` on 401
- [x] JWT blacklist via Redis `bl:*`
- [x] Rate limit `60/min` on `/mcp`
- [ ] RS256 + JWKS + `kid` rotation (next rung)
- [ ] DCR persistence (currently static public client)

## Evidence to capture

- `docs/mcp-evidence/inspector-trace.json`
- `docs/mcp-evidence/claude-desktop-config.json`
- `docs/mcp-evidence/screenshots/{tools-list,tool-call,401}.png`
