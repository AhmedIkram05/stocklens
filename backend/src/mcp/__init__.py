"""StockLens MCP — production-grade Model Context Protocol server.

Exposes the 16 canonical agent tools (src/agent/tools.py) via Streamable HTTP
with OAuth 2.1 + PKCE. Single source of truth: tools are adapted, not duplicated.

Usage:
    from src.mcp.server import mcp_router
    app.include_router(mcp_router)
"""

from __future__ import annotations
