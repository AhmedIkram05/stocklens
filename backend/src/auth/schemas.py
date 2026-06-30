"""
Pydantic request/response schemas for the auth module.

Matches the ``users`` and ``refresh_tokens`` table definitions from
``src.database.schema`` — note that the DB column is ``display_name``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ── Tokens ────────────────────────────────────────────────────────────────────


class TokenPayload(BaseModel):
    """Contents of a decoded JWT."""

    sub: str  # user_id
    jti: str  # unique token identifier (for blacklisting)
    exp: int  # unix timestamp
    iat: int  # unix timestamp
    type: str  # "access" | "refresh"


class TokenPair(BaseModel):
    """Access + refresh token pair returned to the client."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # seconds (default 30 min)


# ── Users ─────────────────────────────────────────────────────────────────────


class UserInDB(BaseModel):
    """Full user record as stored in the database.

    The underlying table column is ``display_name``; we map it to
    ``full_name`` at the API layer for consistency across the frontend.
    """

    id: str
    email: str
    password_hash: str
    display_name: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserPublic(BaseModel):
    """User data safe to return over the API."""

    id: str
    email: str
    display_name: Optional[str] = Field(default=None)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Requests ──────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """New user registration payload."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    """User login payload."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Refresh token request payload."""

    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    """Password reset request payload."""

    email: EmailStr


class LogoutRequest(BaseModel):
    """Logout request payload — the client sends its refresh token
    so it can be revoked server-side.

    The refresh_token field is optional: if provided it will be revoked
    server-side; if omitted only the access token is blacklisted.
    """

    refresh_token: str | None = None


# ── Responses ─────────────────────────────────────────────────────────────────


class AuthResponse(BaseModel):
    """Response returned on successful register / login."""

    user: UserPublic
    tokens: TokenPair


class Message(BaseModel):
    """Simple message response."""

    message: str


# ── Miscellaneous ─────────────────────────────────────────────────────────────


class RefreshTokenRecord(BaseModel):
    """A refresh token row from the ``refresh_tokens`` table."""

    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    revoked: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
