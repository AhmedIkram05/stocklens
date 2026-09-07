"""
GraphQL router — Strawberry FastAPI router with JWT auth (Mechanism A on HTTP).

``context_getter`` is wrapped as ``Depends(...)`` by Strawberry. On HTTP,
``get_current_user`` raises 401/403 before execution — REST parity.
WebSocket handshakes skip header auth and carry an anonymous context:
browsers/RN can't set handshake headers, and HTTPBearer can't resolve in WS
scope (proven by spike — the handshake 500s otherwise). Auth is enforced
per-subscription via ``connection_params`` (see ``_validate_ws_token``).
Rate limit applies on HTTP only.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.security import HTTPBearer
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocket
from strawberry.fastapi import GraphQLRouter

from src.auth.dependencies import get_current_user
from src.config import settings
from src.graphql.schema import schema
from src.limiter import limiter


async def _noop(request: Request) -> None:
    return None


_limited = limiter.limit(settings.RATE_LIMIT_DEFAULT)(_noop)
_bearer = HTTPBearer(auto_error=False)


async def get_graphql_context(request: HTTPConnection) -> dict:
    if isinstance(request, WebSocket):
        # ponytail: anonymous handshake context — WS auth lives in the
        # subscription resolver; handshake not rate limited either
        # (slowapi has no WS support). Revisit if abuse appears.
        return {"request": request, "user_id": None, "children": {}}
    assert isinstance(request, Request)
    # Same primitives as Depends(get_current_user) — identical 401 behaviour.
    current_user = await get_current_user(request=request, credentials=await _bearer(request))
    await _limited(request)

    return {"request": request, "user_id": current_user.id, "children": {}}


graphql_router = GraphQLRouter(
    schema,
    context_getter=get_graphql_context,
    graphql_ide=None,
)
