"""
GraphQL router — Strawberry FastAPI router with JWT auth (Mechanism A).

``context_getter`` is wrapped as ``Depends(...)`` by Strawberry, so
``get_current_user`` raises 401/403 before execution — REST parity.
Rate limit applies on HTTP only.
"""

from __future__ import annotations

from fastapi import Depends, Request
from strawberry.fastapi import GraphQLRouter

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.graphql.schema import schema
from src.limiter import limiter


async def _noop(request: Request) -> None:
    return None


_limited = limiter.limit(settings.RATE_LIMIT_DEFAULT)(_noop)


async def get_graphql_context(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
) -> dict:
    # ponytail: WS handshake not rate limited (slowapi has no WS support);
    # add WS-side limits if abuse appears.
    await _limited(request)

    return {"request": request, "user_id": current_user.id, "children": {}}


graphql_router = GraphQLRouter(
    schema,
    context_getter=get_graphql_context,
    graphql_ide=None,
)
