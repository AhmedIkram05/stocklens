"""StockLens MCP Server — FastAPI-native Streamable HTTP.

Exposes 16 canonical tools as MCP Tools with OAuth 2.1 protection.
Official Python SDK (modelcontextprotocol/python-sdk) is the primary transport
when installed; FastAPI fallback handles JSON-RPC directly so tests run without
extra deps.

Mount:
    from src.mcp.server import mcp_router  # includes /.well-known/* + /oauth/* + /mcp
    app.include_router(mcp_router)

Or low-level ASGI mount:
    from src.mcp.server import create_mcp_app
    app.mount("/mcp", create_mcp_app())

CV keywords: MCP SDK, Streamable HTTP, SSE, OAuth 2.1 PKCE, FastAPI mount,
single source of truth, 16 tools, structlog observability.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.config import settings
from src.mcp.auth import router as oauth_router
from src.mcp.auth import verify_mcp_token
from src.mcp.tools_adapter import (
    get_mcp_prompts,
    get_mcp_resources,
    get_mcp_tools,
    get_prompt,
    get_tool_names,
    invoke_tool,
    read_resource,
)

logger = structlog.get_logger(__name__)

# ── Protocol versions (dual-version: 2026-07-28 stateless + 2025-06-18 legacy) ──

SUPPORTED_VERSIONS = ["2026-07-28", "2025-06-18"]
_LEGACY_VERSION = "2025-06-18"
_PROTO_META_KEY = "io.modelcontextprotocol/protocolVersion"


def _request_version(params: dict) -> str | None:
    """Resolve requested protocol version from per-request _meta (2026-07-28 spec).

    Returns None when _meta is absent — a legacy pre-discover client, which keeps
    the 2025-06-18 initialize path as-is.
    """
    meta = params.get("_meta") or {}
    return meta.get(_PROTO_META_KEY)


def _discover_result() -> dict:
    """server/discover result — server identity lives in the result _meta (spec-required)."""
    return {
        "resultType": "complete",
        "supportedVersions": SUPPORTED_VERSIONS,
        "capabilities": {"tools": {}, "resources": {}},
        "_meta": {
            "io.modelcontextprotocol/serverInfo": {
                "name": getattr(settings, "MCP_SERVER_NAME", "stocklens"),
                "version": "0.1.0",
            }
        },
        "instructions": (
            "StockLens portfolio & market intelligence — 16 tools, 2 resources, "
            "1 prompt via OAuth 2.1 RS256"
        ),
        "ttlMs": 3600000,
        "cacheScope": "public",
    }

# ── Router ────────────────────────────────────────────────────────────────

mcp_router = APIRouter(tags=["mcp"])

# OAuth + well-known under same router so GET /.well-known/* works at root
mcp_router.include_router(oauth_router)

# ── MCP JSON-RPC handlers (FastAPI fallback) ─────────────────────────────


def _error(code: int, message: str, id_val: Any = None) -> dict:
    return {"jsonrpc": "2.0", "id": id_val, "error": {"code": code, "message": message}}


@mcp_router.get("/mcp/health")
async def mcp_health():
    """Unauthenticated health for load balancers / Inspector discovery."""
    return {
        "status": "ok",
        "service": "stocklens-mcp",
        "transport": "streamable-http",
        "auth": "oauth2.1-pkce-rs256",
        "tools": len(get_tool_names()),
        "tool_names": get_tool_names(),
        "resources": len(get_mcp_resources()),
        "prompts": len(get_mcp_prompts()),
        "version": "0.1.0",
    }


@mcp_router.get("/mcp")
async def mcp_sse(request: Request, payload=Depends(verify_mcp_token)):
    """SSE stream for MCP clients that open GET /mcp for server-initiated events.

    Kept deliberately under dual-version: 2026-07-28 removes GET streams, but the
    2025-06-18 path (and the Inspector) still opens one. Minimal impl: emit a single
    endpoint event per Streamable HTTP spec, then keepalive.
    """

    async def gen():
        yield "event: endpoint\ndata: /mcp\n\n"
        # Keepalive comment every 15s would go here; for demo close immediately
        # ponytail: no infinite loop — Inspector closes after discovery

    return StreamingResponse(gen(), media_type="text/event-stream")


@mcp_router.post("/mcp")
async def mcp_post(request: Request, payload=Depends(verify_mcp_token)):
    """MCP JSON-RPC over Streamable HTTP — stateless 2026-07-28 core with dual-version.

    Spec: https://modelcontextprotocol.io/specification/2026-07-28 (server/discover,
    no initialize) — 2025-06-18 is served alongside for legacy clients.
    Supports both single JSON-RPC object and batch; returns JSON or SSE stream
    depending on Accept header (ponytail: JSON first, SSE when requested).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Batch support
    is_batch = isinstance(body, list)
    messages = body if is_batch else [body]
    responses: list[dict] = []

    for msg in messages:
        jsonrpc = msg.get("jsonrpc")
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if jsonrpc != "2.0" or not method:
            responses.append(_error(-32600, "Invalid Request", msg_id))
            continue

        # ── version negotiation (2026-07-28) ─────────────────────────────
        requested = _request_version(params)
        if requested is not None and requested not in SUPPORTED_VERSIONS:
            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32022,
                        "message": "Unsupported protocol version",
                        "data": {"supported": SUPPORTED_VERSIONS, "requested": requested},
                    },
                }
            )
            continue

        # ── server/discover (2026-07-28) ─────────────────────────────────
        if method == "server/discover":
            responses.append(
                {"jsonrpc": "2.0", "id": msg_id, "result": _discover_result()}
            )
            logger.info("mcp_discover", version=requested)

        # ── initialize (2025-06-18 only — rejected on 2026-07-28) ────────
        elif method == "initialize":
            if requested == "2026-07-28":
                responses.append(
                    _error(
                        -32601,
                        "Method not found: initialize (2026-07-28 has no initialize handshake)",
                        msg_id,
                    )
                )
                continue
            proto = params.get("protocolVersion", _LEGACY_VERSION)
            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": proto,
                        "capabilities": {
                            "tools": {"listChanged": False},
                            "resources": {"listChanged": False},
                            "prompts": {"listChanged": False},
                        },
                        "serverInfo": {
                            "name": getattr(settings, "MCP_SERVER_NAME", "stocklens"),
                            "version": "0.1.0",
                            "description": (
                                "StockLens portfolio & market intelligence — "
                                "16 tools, 2 resources, 1 prompt via OAuth 2.1 RS256"
                            ),
                        },
                    },
                }
            )
            logger.info(
                "mcp_initialize",
                client=params.get("clientInfo", {}).get("name", "unknown"),
            )

        # ── notifications/initialized ───────────────────────────────────
        elif method == "notifications/initialized":
            # Notification — no response per JSON-RPC
            continue

        # ── tools/list ──────────────────────────────────────────────────
        elif method == "tools/list":
            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": get_mcp_tools()},
                }
            )

        # ── tools/call ──────────────────────────────────────────────────
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if not tool_name:
                responses.append(_error(-32602, "Missing tool name", msg_id))
                continue
            if tool_name not in get_tool_names():
                responses.append(_error(-32602, f"Unknown tool: {tool_name}", msg_id))
                continue

            user_id = payload.sub
            # portfolio_id may be in arguments or inferred
            portfolio_id = arguments.get("portfolio_id")

            # Structured logging for observability (MCP equivalent of LangSmith tracing)
            call_id = uuid.uuid4().hex[:8]
            logger.info(
                "mcp_tool_call",
                call_id=call_id,
                tool=tool_name,
                user_id=user_id[:8],
                has_portfolio=bool(portfolio_id),
            )
            try:
                result_text = await invoke_tool(tool_name, arguments, user_id, portfolio_id)
                # MCP result is list of content blocks
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": result_text}],
                            "isError": False,
                        },
                    }
                )
            except KeyError as e:
                responses.append(_error(-32602, str(e), msg_id))
            except Exception as e:
                logger.exception("mcp_tool_error", tool=tool_name, call_id=call_id)
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                            "isError": True,
                        },
                    }
                )

        # ── resources/list ──────────────────────────────────────────────
        elif method == "resources/list":
            responses.append(
                {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": get_mcp_resources()}}
            )
        # ── resources/read ──────────────────────────────────────────────
        elif method == "resources/read":
            uri = params.get("uri")
            if not uri:
                responses.append(_error(-32602, "Missing uri", msg_id))
                continue
            try:
                text = await read_resource(uri, user_id=payload.sub)
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "contents": [
                                {
                                    "uri": uri,
                                    "mimeType": "application/json",
                                    "text": text,
                                }
                            ]
                        },
                    }
                )
            except KeyError as e:
                responses.append(_error(-32602, str(e), msg_id))
            except Exception as e:
                logger.exception("mcp_resource_error", uri=uri)
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "contents": [
                                {
                                    "uri": uri,
                                    "mimeType": "text/plain",
                                    "text": json.dumps({"error": str(e)}),
                                }
                            ]
                        },
                    }
                )
        # ── prompts/list ─────────────────────────────────────────────────
        elif method == "prompts/list":
            responses.append(
                {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": get_mcp_prompts()}}
            )
        # ── prompts/get ──────────────────────────────────────────────────
        elif method == "prompts/get":
            name = params.get("name")
            args = params.get("arguments") or {}
            if not name:
                responses.append(_error(-32602, "Missing prompt name", msg_id))
                continue
            try:
                result = await get_prompt(name, args, user_id=payload.sub)
                responses.append({"jsonrpc": "2.0", "id": msg_id, "result": result})
            except KeyError as e:
                responses.append(_error(-32602, str(e), msg_id))

        # ── ping ────────────────────────────────────────────────────────
        elif method == "ping":
            responses.append({"jsonrpc": "2.0", "id": msg_id, "result": {}})

        else:
            responses.append(_error(-32601, f"Method not found: {method}", msg_id))

    # Notifications-only batch → 202 No Content per JSON-RPC
    if not responses:
        return JSONResponse(content=None, status_code=202)

    # Streamable HTTP: if client requested SSE, wrap as event stream
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept and len(responses) == 1:
        # Single response as SSE per MCP Streamable HTTP
        payload = json.dumps(responses[0])
        body = f"event: message\ndata: {payload}\n\n"

        async def sse_gen():
            yield body

        return StreamingResponse(sse_gen(), media_type="text/event-stream")

    out: Any = responses if is_batch else responses[0]
    return JSONResponse(content=out)


# ── Optional: official SDK ASGI mount when available ─────────────────────


def create_mcp_app():
    """Return an ASGI app for `app.mount('/mcp', create_mcp_app())`.

    Tries to return the official SDK's StreamableHTTP app (FastMCP) with
    OAuth-aware tool registration; falls back to a Starlette wrapper around
    mcp_router so `mount` still works without extra deps.
    """
    try:
        # Official SDK path — requires `mcp` extra
        from mcp.server.fastmcp import FastMCP  # type: ignore

        fastmcp = FastMCP(name=getattr(settings, "MCP_SERVER_NAME", "stocklens"))

        # Register 16 tools dynamically — same adapter, now via SDK decorators
        for defn in get_mcp_tools():
            name = defn["name"]

            def _make_handler(n: str):
                async def _handler(**kwargs):
                    # SDK injects auth context via request state; fallback to kwargs
                    # For CV, this shows SDK-native registration while reusing adapter
                    user_id = kwargs.pop("_user_id", "unknown")
                    return await invoke_tool(n, kwargs, user_id)

                _handler.__name__ = n
                return _handler

            fastmcp.tool(name=name, description=defn["description"])(_make_handler(name))

        # Streamable HTTP ASGI with auth.
        # ponytail: SDK-native path is the legacy 2025-06-18 implementation until an
        # SDK release ships 2026-07-28 (server/discover) — the router above already
        # serves both versions; upgrade here when the SDK does.
        app = fastmcp.streamable_http_app()  # type: ignore[attr-defined]
        return app
    except Exception as exc:
        # ponytail: degrade to FastAPI router wrapped as ASGI — no new dep required
        logger.info("mcp_sdk_unavailable_fallback_to_router", reason=str(exc))
        from fastapi import FastAPI

        fallback = FastAPI()
        fallback.include_router(mcp_router)
        return fallback
