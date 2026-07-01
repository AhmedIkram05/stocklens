"""
FastAPI router for authentication endpoints.

Implements JWT-based authentication with refresh-token rotation and
server-side token blacklisting via Redis.

Rate limits (applied via slowapi — values from config.py):
    - ``POST /auth/register``  — 20/minute
    - ``POST /auth/login``     — 20/minute
    - ``POST /auth/refresh``   — 20/minute
    - ``POST /auth/logout``    — 100/minute
    - ``GET  /auth/me``        — 100/minute
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    Message,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserInDB,
    UserPublic,
)
from src.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from src.cache.redis import blacklist_token, is_token_blacklisted
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter

logger = structlog.get_logger()

router = APIRouter()


# ── Helper ────────────────────────────────────────────────────────────────────


def _compute_token_expires_in(exp: int) -> int:
    """Return remaining seconds until *exp* (unix ts), clamped to 0."""
    from datetime import datetime, timezone

    remaining = exp - int(datetime.now(timezone.utc).timestamp())
    return max(remaining, 0)


async def _store_refresh_token(user_id: str, jti: str, exp: int) -> None:
    """Insert a refresh token hash into the database."""
    token_hash = hash_token(jti, user_id)
    async with connection_ctx() as conn:
        await conn.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES ($1::uuid, $2, to_timestamp($3))
            """,
            user_id,
            token_hash,
            exp,
        )


async def _revoke_refresh_token(token_hash: str) -> None:
    """Mark a refresh token row as revoked."""
    async with connection_ctx() as conn:
        await conn.execute(
            "UPDATE refresh_tokens SET revoked = true WHERE token_hash = $1",
            token_hash,
        )


async def _fetch_user_by_email(email: str) -> dict | None:
    """Return a raw user row (or ``None``) for the given *email*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, password_hash, display_name, is_active,
                   created_at, updated_at
            FROM users
            WHERE email = $1
            """,
            email,
        )
    return dict(row) if row else None


def _row_to_user_public(row: dict) -> UserPublic:
    """Convert a raw DB row to a ``UserPublic`` response model."""
    return UserPublic(
        id=str(row["id"]),
        email=row["email"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def register(request: Request, body: RegisterRequest) -> AuthResponse:
    """Register a new user account.

    Creates a user record, issues an access + refresh token pair, and stores
    the refresh token hash in the database.
    """
    # Normalise email
    email = body.email.lower().strip()

    # Check for existing user
    existing = await _fetch_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Hash password and insert
    pwd_hash = hash_password(body.password)
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, display_name)
            VALUES ($1, $2, $3)
            RETURNING id, email, password_hash, display_name, is_active,
                      created_at, updated_at
            """,
            email,
            pwd_hash,
            body.full_name,
        )

    user = dict(row)

    # Create token pair
    user_id = str(user["id"])
    access_token, access_jti = create_access_token(user_id)
    refresh_token, refresh_jti = create_refresh_token(user_id)
    decoded = decode_token(access_token)
    refresh_decoded = decode_token(refresh_token)

    # Persist refresh token with its own 7-day expiry
    await _store_refresh_token(user_id, refresh_jti, refresh_decoded.exp)

    logger.info("user_registered", user_id=user_id, email=email)

    return AuthResponse(
        user=_row_to_user_public(user),
        tokens=TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=_compute_token_expires_in(decoded.exp),
        ),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(request: Request, body: LoginRequest) -> AuthResponse:
    """Authenticate a user and return a token pair."""
    email = body.email.lower().strip()
    user = await _fetch_user_by_email(email)

    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    user_id = str(user["id"])
    access_token, access_jti = create_access_token(user_id)
    refresh_token, refresh_jti = create_refresh_token(user_id)
    decoded = decode_token(access_token)
    refresh_decoded = decode_token(refresh_token)

    await _store_refresh_token(user_id, refresh_jti, refresh_decoded.exp)

    logger.info("user_logged_in", user_id=user_id)

    return AuthResponse(
        user=_row_to_user_public(user),
        tokens=TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=_compute_token_expires_in(decoded.exp),
        ),
    )


@router.post("/forgot-password", response_model=Message)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
) -> Message:
    """Request a password reset email.

    This is a no-op stub — email infrastructure will be added in Phase 5.
    Always returns 200 to avoid revealing whether an account exists.
    """
    email = body.email.lower().strip()
    logger.info("password_reset_requested", email=email)
    return Message(message="If an account exists for that email, we'll send a reset link.")


@router.post("/refresh", response_model=TokenPair)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def refresh(request: Request, body: RefreshRequest) -> TokenPair:
    """Issue a new access + refresh token pair.

    Implements refresh-token rotation: the old refresh token is revoked in the
    database and its associated access token JTI is blacklisted in Redis.
    """
    # Decode the refresh token
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Check Redis blacklist
    if await is_token_blacklisted(payload.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    # Look up the token hash in the database
    token_hash = hash_token(payload.jti, payload.sub)
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, token_hash, expires_at, revoked, created_at
            FROM refresh_tokens
            WHERE token_hash = $1
            """,
            token_hash,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    user_id = str(row["user_id"])

    # ── Stolen-token detection ──────────────────────────────────────────────
    # If the refresh token was *already* revoked, someone is replaying an old
    # token.  Revoke ALL refresh tokens for this user (force re-login).
    if row["revoked"]:
        logger.warning("stolen_token_detected", user_id=user_id)
        async with connection_ctx() as conn:
            await conn.execute(
                "UPDATE refresh_tokens SET revoked = true WHERE user_id = $1::uuid",
                user_id,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    # Revoke old refresh token in DB
    await _revoke_refresh_token(token_hash)

    # Blacklist old refresh JTI in Redis
    await blacklist_token(payload.jti, 86400)  # 24h TTL (well past token expiry)

    # Issue new pair
    new_access_token, new_access_jti = create_access_token(user_id)
    new_refresh_token, new_refresh_jti = create_refresh_token(user_id)
    decoded = decode_token(new_access_token)
    refresh_decoded = decode_token(new_refresh_token)

    await _store_refresh_token(user_id, new_refresh_jti, refresh_decoded.exp)

    logger.info("tokens_refreshed", user_id=user_id)

    return TokenPair(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=_compute_token_expires_in(decoded.exp),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def logout(
    request: Request,
    body: LogoutRequest,
    current_user: UserInDB = Depends(get_current_user),
) -> None:
    """Log out the current user.

    1. Revoke the refresh token in the database (SHA256 hash lookup).
    2. Blacklist the access token in Redis so it cannot be used again.
    3. Return 204 No Content.
    """
    user_id = current_user.id

    # Revoke refresh token in DB (if provided)
    if body.refresh_token:
        try:
            refresh_payload = decode_token(body.refresh_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        if refresh_payload.type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        token_hash = hash_token(refresh_payload.jti, refresh_payload.sub)
        async with connection_ctx() as conn:
            result = await conn.execute(
                "UPDATE refresh_tokens SET revoked = true WHERE token_hash = $1",
                token_hash,
            )
            if result == "UPDATE 0":
                logger.warning(
                    "logout_refresh_token_not_found",
                    user_id=user_id,
                )

    # Blacklist the access token in Redis for its remaining lifetime
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    security = HTTPBearer(auto_error=False)
    credentials: HTTPAuthorizationCredentials | None = await security(request)
    if credentials is not None:
        payload = decode_token(credentials.credentials)
        remaining = _compute_token_expires_in(payload.exp)
        if remaining > 0:
            await blacklist_token(payload.jti, remaining)

    logger.info("user_logged_out", user_id=user_id)


@router.get("/me", response_model=UserPublic)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_me(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
) -> UserPublic:
    """Return the authenticated user's profile."""
    return UserPublic(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )
