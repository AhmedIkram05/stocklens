"""
Tests for configuration settings (src.config.Settings).

Tests cover env var loading, defaults, derived values (REDIS_URL), and validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings


class TestSettingsDefaults:
    """Test default values when env vars are not set."""

    def test_default_database_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert s.DATABASE_URL == "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens"

    def test_default_test_database_url(self, monkeypatch):
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert "postgres_test" in s.TEST_DATABASE_URL

    def test_default_redis_host_port_password(self, monkeypatch):
        for v in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert s.REDIS_HOST == "redis"
        assert s.REDIS_PORT == 6379
        assert s.REDIS_PASSWORD == ""

    def test_default_jwt_algorithm_and_expiry(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert s.JWT_ALGORITHM == "HS256"
        assert s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 30
        assert s.JWT_REFRESH_TOKEN_EXPIRE_DAYS == 7

    def test_default_bcrypt_rounds(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert s.BCRYPT_ROUNDS == 12

    def test_default_cors_origins(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert "localhost:8081" in s.CORS_ORIGINS
        assert "localhost:19006" in s.CORS_ORIGINS

    def test_default_drift_thresholds(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        s = Settings()
        assert s.DRIFT_ALERT_PSI_THRESHOLD == 0.25
        assert s.DRIFT_ALERT_KS_THRESHOLD == 0.3
        assert s.DRIFT_ALERT_JS_THRESHOLD == 0.3


class TestSettingsFromEnv:
    """Test that env vars override defaults."""

    def test_database_url_from_env(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db")
        s = Settings()
        assert s.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_redis_url_derived_from_host_port(self, monkeypatch):
        """REDIS_URL is derived from host/port/password when not set directly."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("REDIS_HOST", "my-redis")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "secret")
        monkeypatch.delenv("REDIS_URL", raising=False)
        s = Settings()
        assert s.REDIS_URL == "rediss://:secret@my-redis:6380/0"

    def test_redis_url_derived_without_password(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("REDIS_HOST", "my-redis")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "")
        monkeypatch.delenv("REDIS_URL", raising=False)
        s = Settings()
        assert s.REDIS_URL == "rediss://my-redis:6380/0"

    def test_redis_url_explicit_overrides_derived(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("REDIS_URL", "redis://explicit:6379/1")
        s = Settings()
        assert s.REDIS_URL == "redis://explicit:6379/1"

    def test_jwt_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "env-secret")
        monkeypatch.setenv("JWT_ALGORITHM", "RS256")
        monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
        monkeypatch.setenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "14")
        s = Settings()
        assert s.JWT_SECRET_KEY == "env-secret"
        assert s.JWT_ALGORITHM == "RS256"
        assert s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 60
        assert s.JWT_REFRESH_TOKEN_EXPIRE_DAYS == 14

    def test_cors_origins_from_env(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://admin.example.com")
        s = Settings()
        assert s.CORS_ORIGINS == "https://app.example.com,https://admin.example.com"

    def test_drift_thresholds_from_env(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("DRIFT_ALERT_PSI_THRESHOLD", "0.1")
        monkeypatch.setenv("DRIFT_ALERT_KS_THRESHOLD", "0.2")
        monkeypatch.setenv("DRIFT_ALERT_JS_THRESHOLD", "0.15")
        s = Settings()
        assert s.DRIFT_ALERT_PSI_THRESHOLD == 0.1
        assert s.DRIFT_ALERT_KS_THRESHOLD == 0.2
        assert s.DRIFT_ALERT_JS_THRESHOLD == 0.15


class TestSettingsValidation:
    """Test validation constraints."""

    def test_jwt_secret_key_required(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings()

    def test_jwt_expiry_positive(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_bcrypt_rounds_positive(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("BCRYPT_ROUNDS", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_drift_thresholds_non_negative(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("DRIFT_ALERT_PSI_THRESHOLD", "-0.1")
        with pytest.raises(ValidationError):
            Settings()

    def test_drift_s3_bucket_allows_empty(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("DRIFT_REPORT_S3_BUCKET", "")
        s = Settings()
        assert s.DRIFT_REPORT_S3_BUCKET == ""

    def test_cascade_thresholds_valid_range(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("CASCADE_CONFIDENCE_THRESHOLD", "0.8")
        monkeypatch.setenv("CASCADE_OCR_CONFIDENCE_FLOOR", "0.5")
        s = Settings()
        assert s.CASCADE_CONFIDENCE_THRESHOLD == 0.8
        assert s.CASCADE_OCR_CONFIDENCE_FLOOR == 0.5


class TestSettingsDerivedValues:
    """Test computed/derived settings."""

    def test_redis_url_uses_rediss_scheme(self, monkeypatch):
        """ElastiCache forces TLS — rediss:// scheme used by default."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("REDIS_HOST", "cache.example.com")
        monkeypatch.setenv("REDIS_PORT", "6379")
        monkeypatch.delenv("REDIS_URL", raising=False)
        s = Settings()
        assert s.REDIS_URL.startswith("rediss://")

    def test_env_guard_allows_development_without_env_file(self, monkeypatch, tmp_path):
        """ENVIRONMENT=development allows missing .env file."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        # Change to temp dir without .env
        import os

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            s = Settings()
            assert s.ENVIRONMENT == "development"
        finally:
            os.chdir(old_cwd)
