"""Route-table dispatch for ``mcp_post`` — logic-level, no DB or HTTP.

The HTTP MCP suite (``tests/test_mcp_server.py``) needs Postgres and runs in CI
only. These pin the method table and each handler's branching directly, so a
dispatch regression is catchable without a database. Each handler is exercised
through ``_METHOD_HANDLERS`` — the same lookup ``mcp_post`` performs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.mcp.auth import McpPrincipal
from src.mcp.server import _METHOD_HANDLERS, _RpcContext

_FULL_SCOPES = McpPrincipal(sub="user-1234", scopes=frozenset({"mcp:tools"}))
_NO_SCOPES = McpPrincipal(sub="user-1234", scopes=frozenset())


def _ctx(params: dict | None = None, principal: McpPrincipal = _FULL_SCOPES, version=None):
    return _RpcContext(
        params=params or {}, msg_id=1, principal=principal, requested_version=version
    )


async def _dispatch(
    method: str, params: dict | None = None, principal=_FULL_SCOPES, version=None
) -> dict:
    result = await _METHOD_HANDLERS[method](_ctx(params, principal, version))
    assert result is not None, f"{method} returned no response"
    return result


class TestDispatchTable:
    """Adding a method is a data change; the table must stay explicit."""

    def test_table_maps_every_supported_method(self):
        assert set(_METHOD_HANDLERS) == {
            "server/discover",
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
            "resources/list",
            "resources/read",
            "prompts/list",
            "prompts/get",
            "ping",
        }

    def test_unknown_method_is_absent(self):
        # mcp_post maps a missing key to -32601 Method not found.
        assert _METHOD_HANDLERS.get("does/not_exist") is None


class TestToolsCall:
    async def test_missing_name_is_32602(self):
        resp = await _dispatch("tools/call", {"arguments": {}})
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "Missing tool name"

    async def test_unknown_tool_is_32602(self):
        with patch("src.mcp.server.get_tool_names", return_value={"get_market_quote"}):
            resp = await _dispatch("tools/call", {"name": "nonexistent_tool"})
        assert resp["error"]["code"] == -32602
        assert "Unknown tool" in resp["error"]["message"]

    async def test_scope_denied_is_32003(self):
        with (
            patch("src.mcp.server.get_tool_names", return_value={"get_market_quote"}),
            patch("src.mcp.server.invoke_tool", new_callable=AsyncMock) as mock_invoke,
        ):
            resp = await _dispatch("tools/call", {"name": "get_market_quote"}, _NO_SCOPES)
        assert resp["error"]["code"] == -32003
        assert resp["error"]["data"]["required_scope"] == "market:read"
        mock_invoke.assert_not_called()

    async def test_happy_path_returns_text_block(self):
        with (
            patch("src.mcp.server.get_tool_names", return_value={"get_market_quote"}),
            patch(
                "src.mcp.server.invoke_tool",
                new_callable=AsyncMock,
                return_value='{"price": 150}',
            ),
        ):
            resp = await _dispatch("tools/call", {"name": "get_market_quote"})
        assert resp["result"]["isError"] is False
        assert resp["result"]["content"][0]["type"] == "text"
        assert "150" in resp["result"]["content"][0]["text"]

    async def test_key_error_from_tool_is_32602(self):
        with (
            patch("src.mcp.server.get_tool_names", return_value={"get_market_quote"}),
            patch(
                "src.mcp.server.invoke_tool",
                new_callable=AsyncMock,
                side_effect=KeyError("boom"),
            ),
        ):
            resp = await _dispatch("tools/call", {"name": "get_market_quote"})
        assert resp["error"]["code"] == -32602
        assert "boom" in resp["error"]["message"]

    async def test_generic_exception_is_opaque_iserror(self):
        with (
            patch("src.mcp.server.get_tool_names", return_value={"get_market_quote"}),
            patch(
                "src.mcp.server.invoke_tool",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db constraint secret"),
            ),
        ):
            resp = await _dispatch("tools/call", {"name": "get_market_quote"})
        assert resp["result"]["isError"] is True
        # Raw exception text must not leak to the client.
        assert "constraint secret" not in resp["result"]["content"][0]["text"]


class TestInitializeAndDiscover:
    async def test_discover_result(self):
        resp = await _dispatch("server/discover", version="2026-07-28")
        assert resp["result"]["supportedVersions"]
        assert resp["result"]["ttlMs"] == 3600000

    async def test_initialize_legacy_returns_protocol_version(self):
        resp = await _dispatch("initialize", {"protocolVersion": "2025-06-18"})
        assert resp["result"]["protocolVersion"] == "2025-06-18"

    async def test_initialize_rejected_on_2026(self):
        resp = await _dispatch("initialize", version="2026-07-28")
        assert resp["error"]["code"] == -32601


class TestOtherMethods:
    async def test_notification_returns_none(self):
        handler = _METHOD_HANDLERS["notifications/initialized"]
        assert await handler(_ctx()) is None

    async def test_ping(self):
        resp = await _dispatch("ping")
        assert resp["result"] == {}

    async def test_tools_list_filters_by_scope(self):
        tools = [
            {"name": "get_portfolio_summary"},
            {"name": "get_market_quote"},
        ]
        with patch("src.mcp.server.get_mcp_tools", return_value=tools):
            resp = await _dispatch("tools/list", principal=_NO_SCOPES)
        assert resp["result"]["tools"] == []

    async def test_resources_list(self):
        with patch("src.mcp.server.get_mcp_resources", return_value=[{"uri": "x"}]):
            resp = await _dispatch("resources/list")
        assert resp["result"]["resources"] == [{"uri": "x"}]

    async def test_resources_read_missing_uri(self):
        resp = await _dispatch("resources/read", {})
        assert resp["error"]["code"] == -32602

    async def test_resources_read_scope_denied(self):
        resp = await _dispatch("resources/read", {"uri": "portfolio://holdings"}, _NO_SCOPES)
        assert resp["error"]["code"] == -32003
        assert resp["error"]["data"]["required_scope"] == "portfolio:read"

    async def test_resources_read_key_error_is_32602(self):
        with patch(
            "src.mcp.server.read_resource",
            new_callable=AsyncMock,
            side_effect=KeyError("Unknown resource"),
        ):
            resp = await _dispatch("resources/read", {"uri": "portfolio://holdings"})
        assert resp["error"]["code"] == -32602

    async def test_prompts_list(self):
        with patch("src.mcp.server.get_mcp_prompts", return_value=[{"name": "p"}]):
            resp = await _dispatch("prompts/list")
        assert resp["result"]["prompts"] == [{"name": "p"}]

    async def test_prompts_get_missing_name(self):
        resp = await _dispatch("prompts/get", {})
        assert resp["error"]["code"] == -32602

    async def test_prompts_get_scope_denied(self):
        resp = await _dispatch("prompts/get", {"name": "analyze-portfolio"}, _NO_SCOPES)
        assert resp["error"]["code"] == -32003

    async def test_prompts_get_happy_path(self):
        with patch(
            "src.mcp.server.get_prompt",
            new_callable=AsyncMock,
            return_value={"messages": []},
        ):
            resp = await _dispatch("prompts/get", {"name": "analyze-portfolio"})
        assert resp["result"] == {"messages": []}


@pytest.mark.parametrize("method", sorted(_METHOD_HANDLERS))
async def test_every_handler_is_callable(method: str):
    """A table entry must resolve to a callable handler."""
    assert callable(_METHOD_HANDLERS[method])
