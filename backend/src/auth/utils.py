"""
JWT and password hashing utilities for the auth module.

Uses ``bcrypt`` for password hashing and ``PyJWT`` for token creation /
validation, both of which are already declared in ``pyproject.toml``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Tuple
from uuid import uuid4

import bcrypt
import jwt

from src.auth.schemas import TokenPayload
from src.config import settings

# ── Password hashing ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return ``True`` if *password* matches the stored *password_hash*."""
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


# ── Token creation ────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str) -> Tuple[str, str]:
    """Create an HS256 signed access JWT.

    Returns
    -------
    (token, jti)
        The encoded JWT string and its unique identifier (for blacklisting).
    """
    jti = uuid4().hex
    now = _now_utc()
    exp = int((now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp())

    payload = {
        "sub": user_id,
        "jti": jti,
        "exp": exp,
        "iat": int(now.timestamp()),
        "type": "access",
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def create_refresh_token(user_id: str) -> Tuple[str, str]:
    """Create an HS256 signed refresh JWT with longer expiry.

    Returns
    -------
    (token, jti)
        The encoded JWT string and its unique identifier (for storage / lookup).
    """
    jti = uuid4().hex
    now = _now_utc()
    exp = int((now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)).timestamp())

    payload = {
        "sub": user_id,
        "jti": jti,
        "exp": exp,
        "iat": int(now.timestamp()),
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


# ── Token decoding ────────────────────────────────────────────────────────────


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT.

    Raises
    ------
    jwt.ExpiredSignatureError
        If the token has expired.
    jwt.InvalidTokenError
        If the token is malformed or the signature is invalid.
    """
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    return TokenPayload(**payload)


# ── Refresh token hashing (for DB lookup) ─────────────────────────────────────


def hash_token(jti: str, user_id: str) -> str:
    """Return a SHA-256 hex digest of ``{jti}:{user_id}`` for storage in
    ``refresh_tokens.token_hash``.

    The compound input binds the token to its owning user as defense-in-depth.
    """
    return hashlib.sha256(f"{jti}:{user_id}".encode("utf-8")).hexdigest()
