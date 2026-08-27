"""Adapter: LangChain StructuredTool → MCP Tool definition.

Single source of truth: every MCP tool delegates to the canonical
implementation in src/agent/tools.py via StructuredTool.ainvoke().

InjectedState fields (user_id, portfolio_id) are stripped from the
MCP inputSchema — they're injected server-side from the verified JWT,
never exposed to the LLM/client.

Portfolio resolution: if a portfolio-scoped tool is called without
portfolio_id, the adapter resolves the user's default portfolio
(oldest created) via DB — mirrors AgentService._resolve_portfolio_id.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import structlog

from src.agent.tools import get_all_tools

logger = structlog.get_logger(__name__)

# Fields injected from auth context — never exposed in MCP schema.
_INJECTED = {"user_id", "portfolio_id"}

# Cache of LangChain tools keyed by name
_TOOLS: dict[str, Any] | None = None


def _load_tools() -> dict[str, Any]:
    global _TOOLS
    if _TOOLS is None:
        _TOOLS = {t.name: t for t in get_all_tools()}
    return _TOOLS


def _strip_injected(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove injected fields from a JSON Schema.

    Handles both top-level properties and required lists. Preserves
    original schema immutability by shallow-copying.
    """
    if not schema or "properties" not in schema:
        return schema
    props = {k: v for k, v in schema["properties"].items() if k not in _INJECTED}
    required = [r for r in schema.get("required", []) if r not in _INJECTED]
    out = dict(schema)
    out["properties"] = props
    if required:
        out["required"] = required
    elif "required" in out:
        out.pop("required", None)
    # Ensure additionalProperties is explicit for MCP strictness
    out.setdefault("type", "object")
    return out


def get_mcp_tools() -> list[dict[str, Any]]:
    """Return MCP-compatible tool definitions for all 16 canonical tools.

    Each entry: {name, description, inputSchema}
    inputSchema is JSON Schema with injected fields stripped.
    """
    definitions: list[dict[str, Any]] = []
    for tool in _load_tools().values():
        # LangChain StructuredTool exposes .args_schema (Pydantic) or .args
        raw_schema: dict[str, Any] = {}
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            try:
                raw_schema = tool.args_schema.model_json_schema()  # Pydantic v2
            except Exception:
                raw_schema = getattr(tool, "args", {}) or {}
        elif hasattr(tool, "args"):
            raw_schema = getattr(tool, "args", {}) or {}

        # Fallback: if schema extraction failed, build minimal object schema
        if not raw_schema or "properties" not in raw_schema:
            # Try tool.get_input_schema()
            try:
                if hasattr(tool, "get_input_schema"):
                    pydantic_schema = tool.get_input_schema()
                    raw_schema = pydantic_schema.model_json_schema()
            except Exception:
                raw_schema = {"type": "object", "properties": {}}

        input_schema = _strip_injected(raw_schema)
        definitions.append(
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "inputSchema": input_schema,
            }
        )
    # Deterministic ordering for stable MCP list_tools
    definitions.sort(key=lambda d: d["name"])
    return definitions


def get_tool_names() -> list[str]:
    """Return sorted canonical tool names — used in tests/health."""
    return sorted(_load_tools().keys())


async def resolve_portfolio_id(user_id: str, explicit: str | None = None) -> str:
    """Resolve portfolio_id: explicit arg or user's default (first created).

    Returns "" if user has no portfolios — caller should surface
    "Portfolio not found" via tool response rather than 4xx.
    """
    if explicit:
        return explicit
    try:
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM portfolios WHERE user_id = $1::uuid "
                "ORDER BY created_at ASC LIMIT 1",
                user_id,
            )
        return str(row["id"]) if row else ""
    except Exception:
        logger.warning("portfolio_resolve_failed", user_id=user_id[:8])
        return ""


async def invoke_tool(
    name: str,
    arguments: dict[str, Any],
    user_id: str,
    portfolio_id: str | None = None,
) -> str:
    """Invoke a canonical tool with auth-injected context.

    Returns the tool's JSON string output (already json.dumps'd by the tool).
    Raises KeyError if tool not found; propagates tool exceptions as JSON error.

    ponytail: one adapter, not 16 wrappers — same path as AgentService graph.
    """
    tools = _load_tools()
    tool = tools.get(name)
    if tool is None:
        raise KeyError(f"Unknown tool: {name}")

    # Inject auth context — LangChain InjectedState fields
    payload: dict[str, Any] = dict(arguments or {})

    # Always inject user_id (every tool requires it)
    payload["user_id"] = user_id

    # Portfolio-scoped tools: inject portfolio_id if schema expects it
    # Detect by checking if original schema had portfolio_id (before stripping)
    needs_portfolio = False
    try:
        raw = tool.args_schema.model_json_schema() if hasattr(tool, "args_schema") and tool.args_schema else {}
        needs_portfolio = "portfolio_id" in (raw.get("properties") or {})
    except Exception:
        # Conservative fallback: if tool name suggests portfolio scope
        needs_portfolio = name.startswith("get_portfolio") or name in {
            "get_sector_exposure",
            "get_portfolio_diversification_score",
            "get_spending_analysis",
            "get_recent_transactions",
            "get_cash_flow_summary",
            "get_portfolio_performance",
            "compare_to_benchmark",
        }

    if needs_portfolio:
        resolved = await resolve_portfolio_id(user_id, payload.get("portfolio_id") or portfolio_id)
        payload["portfolio_id"] = resolved

    # LangChain @tool expects kwargs, ainvoke handles validation/coercion
    try:
        result: str = await tool.ainvoke(payload)
        # Tool already returns json.dumps(...); ensure string
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
        return result
    except Exception as e:
        logger.exception("mcp_tool_invoke_failed", tool=name, error=str(e))
        return json.dumps({"error": f"Tool {name} failed: {e}"}, default=str)
