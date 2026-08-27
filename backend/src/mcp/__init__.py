"""StockLens MCP — production-grade Model Context Protocol server.

Exposes the 16 canonical agent tools (src/agent/tools.py) via Streamable HTTP
with OAuth 2.1 + PKCE. Single source of truth: tools are adapted, not duplicated.

Usage:
    from src.mcp.server import create_mcp_router  # FastAPI router
    app.include_router(create_mcp_router())

    # Or ASGI mount:
    from src.mcp.server import create_mcp_app
    app.mount("/mcp", create_mcp_app())
"""

from __future__ import annotations
