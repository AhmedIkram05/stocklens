"""
FastAPI dependencies for authentication and authorisation.

Provides ``get_current_user`` (the primary dependency), ``get_current_user_id``,
and ``require_active_user`` for use in endpoint declarations.
"""

from __future__ import annotations

import jwt as pyjwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.schemas import TokenPayload, UserInDB
from src.auth.utils import decode_token
from src.cache.redis import is_token_blacklisted
from src.database.connection import connection_ctx

logger = structlog.get_logger()

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserInDB:
    """Validate the Bearer token and return the authenticated user.

    Verification order:
    1. Extract Bearer token from the ``Authorization`` header.
    2. Decode and validate the JWT (signature, expiry).
    3. Check that the JTI is not blacklisted (logged-out or rotated).
    4. Load the user from the database.
    5. Return the ``UserInDB`` record.

    Raises
    ------
    HTTPException 401
        If the token is missing, invalid, expired, or blacklisted, or if the
        user does not exist.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Step 1 — decode JWT
    try:
        payload: TokenPayload = decode_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # Step 2 — only access tokens may authenticate
    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Step 3 — check Redis blacklist
    if await is_token_blacklisted(payload.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    # Step 4 — fetch user from DB
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, password_hash, display_name, is_active,
                   created_at, updated_at
            FROM users
            WHERE id = $1::uuid
            """,
            payload.sub,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return UserInDB(
        id=str(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_current_user_id(
    current_user: UserInDB = Depends(get_current_user),
) -> str:
    """Return the authenticated user's ID (a convenience shorthand)."""
    return current_user.id


async def require_active_user(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    """Ensure the authenticated user has ``is_active = True``.

    Raises HTTPException 403 if the user's account has been deactivated.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return current_user
