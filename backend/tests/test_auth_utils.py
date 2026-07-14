"""Unit tests for auth/utils.py — password hashing and JWT creation/validation.

Uses real bcrypt + PyJWT (no mocking) since these are thin wrappers.
Uses monkeypatch for settings values.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pytest
from freezegun import freeze_time

from src.auth.schemas import TokenPayload
from src.auth.utils import (
    _now_utc,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)

# ── Password hashing ─────────────────────────────────────────────────────────


class TestHashPassword:
    def test_returns_string(self):
        h = hash_password("MyP@ssword1")
        assert isinstance(h, str)
        assert len(h) > 10

    def test_different_salts_produce_different_hashes(self):
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2

    def test_verify_matches(self):
        pw = "CorrectHorseBatteryStaple1"
        h = hash_password(pw)
        assert verify_password(pw, h) is True

    def test_verify_rejects_wrong_password(self):
        h = hash_password("real-password")
        assert verify_password("wrong-password", h) is False

    def test_verify_rejects_empty(self):
        h = hash_password("real-password")
        assert verify_password("", h) is False

    def test_verify_correct_hash_backward_compat(self):
        """Ensure bcrypt 5.x still verifies a known-good hash string."""
        known_hash = bcrypt.hashpw(b"test", bcrypt.gensalt()).decode()
        assert verify_password("test", known_hash) is True

    def test_handles_unicode(self):
        pw = "pässwörd🚀"
        h = hash_password(pw)
        assert verify_password(pw, h) is True
        assert verify_password("pässwörd", h) is False


class TestVerifyPassword:
    def test_exact_match(self):
        h = hash_password("ExactMatch1!")
        assert verify_password("ExactMatch1!", h)

    def test_case_sensitive(self):
        h = hash_password("UpperCase")
        assert verify_password("uppercase", h) is False

    def test_with_long_password(self):
        long = "a" * 100 + "B1!"
        h = hash_password(long)
        assert verify_password(long, h)

    def test_with_empty_hash_returns_false(self):
        assert verify_password("anything", "") is False


# ── Token creation ────────────────────────────────────────────────────────────


class TestCreateAccessToken:
    def test_returns_token_and_jti(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        token, jti = create_access_token("user-123")
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(jti) == 32  # uuid4 hex

    def test_contains_correct_claims(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        now = datetime.now(timezone.utc)
        with freeze_time(now):
            token, jti = create_access_token("user-456")
            payload = jwt.decode(token, "test-secret", algorithms=["HS256"])

        assert payload["sub"] == "user-456"
        assert payload["jti"] == jti
        assert payload["type"] == "access"
        assert payload["iat"] == int(now.timestamp())
        assert payload["exp"] == int((now + timedelta(minutes=30)).timestamp())

    def test_different_user_ids(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        t1, _ = create_access_token("user-a")
        t2, _ = create_access_token("user-b")
        assert t1 != t2

    def test_minimum_expiry(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 1)

        token, _ = create_access_token("user-1")
        decoded = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert decoded["exp"] > int(datetime.now(timezone.utc).timestamp())


class TestCreateRefreshToken:
    def test_returns_token_and_jti(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS", 30)

        token, jti = create_refresh_token("user-123")
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(jti) == 32

    def test_refresh_has_longer_expiry(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)
        monkeypatch.setattr("src.auth.utils.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS", 30)

        now = datetime.now(timezone.utc)
        with freeze_time(now):
            _, access_jti = create_access_token("user-1")
            _, refresh_jti = create_refresh_token("user-1")
            refresh_token, _ = create_refresh_token("user-1")

        decoded = jwt.decode(refresh_token, "test-secret", algorithms=["HS256"])
        assert decoded["type"] == "refresh"
        assert decoded["exp"] > int((now + timedelta(hours=1)).timestamp())  # much longer
        assert access_jti != refresh_jti  # different JTIs

    def test_correct_type_claim(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)

        token, _ = create_refresh_token("user-1")
        decoded = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert decoded["type"] == "refresh"


# ── Token decoding ────────────────────────────────────────────────────────────


class TestDecodeToken:
    def test_decodes_valid_access_token(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

        token, jti = create_access_token("user-999")
        payload = decode_token(token)

        assert isinstance(payload, TokenPayload)
        assert payload.sub == "user-999"
        assert payload.jti == jti
        assert payload.type == "access"

    def test_decodes_valid_refresh_token(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("src.auth.utils.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)

        token, _ = create_refresh_token("user-999")
        payload = decode_token(token)
        assert payload.type == "refresh"

    def test_raises_on_expired_token(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")

        # Create a token that expired 1 second ago

        expired = jwt.encode(
            {
                "sub": "user-x",
                "jti": "expired-jti",
                "exp": int(datetime.now(timezone.utc).timestamp()) - 1,
                "iat": int(datetime.now(timezone.utc).timestamp()) - 3600,
                "type": "access",
            },
            "test-secret",
            algorithm="HS256",
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(expired)

    def test_raises_on_invalid_signature(self, monkeypatch):
        monkeypatch.setattr("src.auth.utils.settings.JWT_SECRET_KEY", "test-secret")
        monkeypatch.setattr("src.auth.utils.settings.JWT_ALGORITHM", "HS256")

        token, _ = create_access_token("user-1")
        tampered = token[:-5] + "XXXXX"

        with pytest.raises(jwt.InvalidTokenError):
            decode_token(tampered)

    def test_raises_on_malformed_token(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("not-a-token")

    def test_raises_on_empty_string(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("")


# ── Token hashing ─────────────────────────────────────────────────────────────


class TestHashToken:
    def test_returns_hex_string(self):
        result = hash_token("some-jti", "user-123")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex

    def test_deterministic(self):
        r1 = hash_token("abc", "user-1")
        r2 = hash_token("abc", "user-1")
        assert r1 == r2

    def test_different_jti(self):
        r1 = hash_token("jti-a", "user-1")
        r2 = hash_token("jti-b", "user-1")
        assert r1 != r2

    def test_different_user(self):
        r1 = hash_token("same-jti", "user-a")
        r2 = hash_token("same-jti", "user-b")
        assert r1 != r2

    def test_format(self):
        result = hash_token("my-jti", "my-user")
        expected = hashlib.sha256("my-jti:my-user".encode()).hexdigest()
        assert result == expected


# ── Helpers ────────────────────────────────────────────────────────────────────


class TestNowUtc:
    def test_returns_aware_datetime(self):
        now = _now_utc()
        assert now.tzinfo is not None
        assert now.tzinfo.utcoffset(now) == timedelta(0)
