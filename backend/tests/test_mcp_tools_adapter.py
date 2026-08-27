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


@pytest.mark.asyncio
async def test_invoke_tool_portfolio_injection():
    mock_tool = MagicMock()
    mock_tool.name = "get_portfolio_summary"
    # Simulate args_schema with portfolio_id property
    schema_mock = MagicMock()
    schema_mock.model_json_schema.return_value = {
        "properties": {"portfolio_id": {"type": "string"}, "user_id": {"type": "string"}},
        "required": ["portfolio_id", "user_id"],
        "type": "object",
    }
    mock_tool.args_schema = schema_mock
    mock_tool.ainvoke = AsyncMock(return_value=json.dumps({"ok": True}))

    with patch("src.mcp.tools_adapter._load_tools", return_value={"get_portfolio_summary": mock_tool}), patch(
        "src.mcp.tools_adapter.resolve_portfolio_id", new_callable=AsyncMock, return_value="portfolio-999"
    ) as mock_resolve:
        await invoke_tool("get_portfolio_summary", {}, user_id="u1")
        assert mock_resolve.called
        kwargs = mock_tool.ainvoke.call_args[0][0]
        assert kwargs["portfolio_id"] == "portfolio-999"
        assert kwargs["user_id"] == "u1"


@pytest.mark.asyncio
async def test_invoke_tool_error_returns_json():
    mock_tool = MagicMock()
    mock_tool.name = "get_market_quote"
    mock_tool.args_schema = None
    mock_tool.args = {"properties": {"ticker": {"type": "string"}}, "type": "object"}
    mock_tool.get_input_schema = MagicMock(side_effect=Exception("no schema"))
    mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("yfinance down"))

    with patch("src.mcp.tools_adapter._load_tools", return_value={"get_market_quote": mock_tool}):
        result = await invoke_tool("get_market_quote", {"ticker": "AAPL"}, user_id="u1")
        data = json.loads(result)
        assert "error" in data
        assert "yfinance down" in data["error"]


def test_strip_injected_removes_required():
    from src.mcp.tools_adapter import _strip_injected

    schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "user_id": {"type": "string"},
            "portfolio_id": {"type": "string"},
        },
        "required": ["ticker", "user_id", "portfolio_id"],
    }
    out = _strip_injected(schema)
    assert "user_id" not in out["properties"]
    assert "portfolio_id" not in out["properties"]
    assert "ticker" in out["properties"]
    assert out["required"] == ["ticker"]
    # original untouched
    assert "user_id" in schema["properties"]


def test_get_mcp_tools_schema_via_args_schema():
    from unittest.mock import MagicMock, patch

    mock_schema = MagicMock()
    mock_schema.model_json_schema.return_value = {
        "type": "object",
        "properties": {"ticker": {"type": "string"}, "user_id": {"type": "string"}},
        "required": ["ticker", "user_id"],
    }
    mock_tool = MagicMock()
    mock_tool.name = "test_tool"
    mock_tool.description = "test desc"
    mock_tool.args_schema = mock_schema

    with patch("src.mcp.tools_adapter._load_tools", return_value={"test_tool": mock_tool}):
        defs = get_mcp_tools()
        assert len(defs) == 1
        assert defs[0]["name"] == "test_tool"
        assert "user_id" not in defs[0]["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_resolve_portfolio_explicit():
    from src.mcp.tools_adapter import resolve_portfolio_id

    # explicit wins without DB
    pid = await resolve_portfolio_id("user-1", explicit="explicit-pid")
    assert pid == "explicit-pid"

def test_get_mcp_resources():
    from src.mcp.tools_adapter import get_mcp_resources
    resources = get_mcp_resources()
    assert len(resources) == 2
    uris = {r["uri"] for r in resources}
    assert "portfolio://holdings" in uris
    assert all("mimeType" in r for r in resources)


@pytest.mark.asyncio
async def test_read_resource_holdings():
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools_adapter import read_resource
    with patch("src.mcp.tools_adapter.invoke_tool", new_callable=AsyncMock) as mock:
        mock.return_value = '{"holdings": []}'
        text = await read_resource("portfolio://holdings", user_id="u1")
        assert "holdings" in text
        mock.assert_called_once()


@pytest.mark.asyncio
async def test_read_resource_unknown():
    import pytest

    from src.mcp.tools_adapter import read_resource
    with pytest.raises(KeyError):
        await read_resource("unknown://x", user_id="u1")


def test_get_mcp_prompts():
    from src.mcp.tools_adapter import get_mcp_prompts
    prompts = get_mcp_prompts()
    assert len(prompts) == 1
    assert prompts[0]["name"] == "analyze-portfolio"
    assert "arguments" in prompts[0]


@pytest.mark.asyncio
async def test_get_prompt():
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools_adapter import get_prompt
    with patch("src.mcp.tools_adapter.invoke_tool", new_callable=AsyncMock, return_value='{"summary": "ok"}'), patch("src.mcp.tools_adapter.resolve_portfolio_id", new_callable=AsyncMock, return_value="pid-123"):
        result = await get_prompt("analyze-portfolio", {"focus": "risk"}, user_id="u1")
        assert "messages" in result
        assert "pid-123" in result["messages"][0]["content"]["text"]
        assert "risk" in result["messages"][0]["content"]["text"].lower()


@pytest.mark.asyncio
async def test_get_prompt_unknown():
    import pytest

    from src.mcp.tools_adapter import get_prompt
    with pytest.raises(KeyError):
        await get_prompt("unknown", {}, user_id="u1")
