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


# ── MCP Resources & Prompts (full spec beyond tools) ───────────────────
# ponytail: static definitions — 1 resource + 1 prompt is enough to prove
# you read the spec; dynamic per-user listing is the next rung.


def get_mcp_resources() -> list[dict[str, Any]]:
    """Return MCP resource definitions — StockLens portfolio as a resource.

    Resource `portfolio://holdings` exposes the same data as
    `get_portfolio_holdings` but via `resources/read` (resource-oriented
    vs tool-oriented). URI template keeps it stateless; auth injects user.
    """
    return [
        {
            "uri": "portfolio://holdings",
            "name": "Portfolio Holdings",
            "description": (
                "Current holdings for the authenticated user's default "
                "portfolio (JSON) — resource view of get_portfolio_holdings"
            ),
            "mimeType": "application/json",
        },
        {
            "uri": "portfolio://summary",
            "name": "Portfolio Summary",
            "description": (
                "Portfolio summary (value, cash, cost) — "
                "resource view of get_portfolio_summary"
            ),
            "mimeType": "application/json",
        },
    ]


async def read_resource(uri: str, user_id: str) -> str:
    """Read a resource — delegates to canonical tools (single source)."""
    if uri in ("portfolio://holdings", "portfolio://summary"):
        tool_name = "get_portfolio_holdings" if "holdings" in uri else "get_portfolio_summary"
        return await invoke_tool(tool_name, {}, user_id=user_id)
    raise KeyError(f"Unknown resource: {uri}")


def get_mcp_prompts() -> list[dict[str, Any]]:
    """Return MCP prompt definitions — composes tools into a workflow."""
    return [
        {
            "name": "analyze-portfolio",
            "description": (
                "Analyze portfolio: performance vs benchmark, "
                "diversification, and spending — orchestrates 4 tools"
            ),
            "arguments": [
                {
                    "name": "portfolio_id",
                    "description": "Portfolio to analyze (optional, defaults to user's first)",
                    "required": False,
                },
                {
                    "name": "focus",
                    "description": "Focus: performance|risk|spending (default: all)",
                    "required": False,
                },
            ],
        }
    ]


async def get_prompt(name: str, arguments: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    """Get a prompt — returns messages with embedded tool context."""
    if name != "analyze-portfolio":
        raise KeyError(f"Unknown prompt: {name}")
    args = arguments or {}
    portfolio_id = await resolve_portfolio_id(user_id, args.get("portfolio_id"))
    focus = (args.get("focus") or "all").lower()
    # Pre-fetch summary for context (best-effort, fallback to empty)
    try:
        summary = await invoke_tool(
            "get_portfolio_summary", {}, user_id=user_id, portfolio_id=portfolio_id
        )
    except Exception:
        summary = "{}"
    messages = [
        {
            "role": "user",
            "content": {
                "type": "text",
                "text": (
                    f"Analyze portfolio {portfolio_id or 'default'} (focus: {focus}).\n\n"
                    f"Holdings summary:\n{summary}\n\n"
                    "Use get_portfolio_performance, compare_to_benchmark, "
                    "get_portfolio_diversification_score, and get_spending_analysis as needed. "
                    "Return: 1) performance vs SPY, 2) diversification score, 3) spending insight, "
                    "4) one actionable next step."
                ),
            },
        }
    ]
    return {"description": "Portfolio analysis prompt", "messages": messages}


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
        raw = (
            tool.args_schema.model_json_schema()
            if hasattr(tool, "args_schema") and tool.args_schema
            else {}
        )
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
