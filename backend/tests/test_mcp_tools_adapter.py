"""Tests for MCP tools adapter — single source of truth.

Verifies that MCP tool defs are derived from canonical LangChain tools,
injected fields are stripped, and invoke_tool injects auth context.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.tools_adapter import get_mcp_tools, get_tool_names, invoke_tool


def test_tool_names_sorted_and_16():
    names = get_tool_names()
    assert len(names) == 16
    assert names == sorted(names)
    assert "get_portfolio_summary" in names
    assert "get_market_quote" in names


def test_mcp_tools_strip_injected_fields():
    defs = get_mcp_tools()
    assert len(defs) == 16
    by_name = {d["name"]: d for d in defs}
    # Portfolio tools had portfolio_id/user_id stripped
    summary = by_name["get_portfolio_summary"]
    props = summary["inputSchema"].get("properties", {})
    assert "user_id" not in props
    assert "portfolio_id" not in props
    # Market tools never had portfolio_id, but user_id still stripped
    quote = by_name["get_market_quote"]
    qprops = quote["inputSchema"].get("properties", {})
    assert "user_id" not in qprops
    assert "ticker" in qprops  # real arg preserved


def test_mcp_tools_have_descriptions():
    for d in get_mcp_tools():
        assert d["description"], f"{d['name']} missing description"
        assert "inputSchema" in d
        assert d["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_invoke_tool_injects_user_id():
    # Mock the canonical tool's ainvoke
    mock_tool = MagicMock()
    mock_tool.name = "get_market_quote"
    mock_tool.description = "Get quote"
    mock_tool.args_schema = None
    mock_tool.args = {"properties": {"ticker": {"type": "string"}}, "type": "object"}
    mock_tool.get_input_schema = MagicMock(side_effect=Exception("no schema"))
    mock_tool.ainvoke = AsyncMock(return_value=json.dumps({"price": 123}))

    with patch("src.mcp.tools_adapter._load_tools", return_value={"get_market_quote": mock_tool}):
        result = await invoke_tool("get_market_quote", {"ticker": "AAPL"}, user_id="user-123")
    assert json.loads(result)["price"] == 123
    # Verify injection
    assert mock_tool.ainvoke.called
    kwargs = mock_tool.ainvoke.call_args[0][0]
    assert kwargs["user_id"] == "user-123"
    assert kwargs["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_invoke_tool_unknown_raises():
    with pytest.raises(KeyError, match="Unknown tool"):
        await invoke_tool("nope", {}, user_id="u1")
