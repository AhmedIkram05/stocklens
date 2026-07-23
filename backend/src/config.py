import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens"
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://stocklens:stocklens@postgres_test:5432/stocklens_test"
    )

    # Redis — derived from host/port/password when REDIS_URL not set directly
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = ""

    # JWT
    JWT_SECRET_KEY: str = Field(..., min_length=1)  # required, must be non-empty
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    BCRYPT_ROUNDS: int = Field(default=12, gt=0)

    # AWS
    AWS_REGION: str = "eu-west-2"

    # NLP Bedrock Model — Nova Lite: 300K context, $0.06/$0.24 per 1M tokens
    BEDROCK_MODEL_ID: str = "amazon.nova-lite-v1:0"

    # OCR
    OCR_TESSERACT_CMD: str | None = None

    # Rate Limiting
    RATE_LIMIT_LOGIN: str = "20/minute"
    RATE_LIMIT_DEFAULT: str = "100/minute"

    # CORS — comma-separated list of allowed origins
    CORS_ORIGINS: str = "http://localhost:8081,http://localhost:19006,exp://127.0.0.1:19000"

    # Logging
    STRUCTLOG_LOG_LEVEL: str = "INFO"

    # Environment
    ENVIRONMENT: str = "development"

    # Performance
    ENABLE_TWR: bool = True

    # Champion S3 delivery
    CHAMPION_S3_URI: str = ""

    # Prediction
    PREDICTION_MODEL_PATH: str = "/model_artifacts/champion/model.pt"
    PREDICTION_CACHE_TTL: int = 21600
    PREDICTION_SERVING_BACKEND: str = "fargate"  # "fargate" | "sagemaker"
    SAGEMAKER_ENDPOINT_NAME: str = "stocklens-prediction-production-dev"

    # Prediction Logging / Drift
    PREDICTION_LOG_ENABLED: bool = True
    PREDICTION_LOG_RETENTION_DAYS: int = 90
    DRIFT_ALERT_PSI_THRESHOLD: float = Field(default=0.25, ge=0)
    DRIFT_ALERT_KS_THRESHOLD: float = Field(default=0.3, ge=0)
    DRIFT_ALERT_JS_THRESHOLD: float = Field(default=0.3, ge=0)
    DRIFT_MONITORED_TICKERS: str = ""  # comma-separated, empty = portfolio-only
    DRIFT_REPORT_S3_BUCKET: str = "stocklens-drift-reports-dev"
    DRIFT_REPORT_S3_PREFIX: str = "drift_reports/"

    # Agent
    # Nova Lite: 300K context, tool-use capable, $0.06/$0.24 per 1M tokens
    AGENT_MODEL_ID: str = "amazon.nova-lite-v1:0"
    # GLM-4.7 Flash: $0.07/$0.40 — 93% cheaper input, 88% cheaper output than GLM-5
    AGENT_JUDGE_MODEL_ID: str = "zai.glm-4.7-flash"
    # NLP pipeline — Nova Lite: 300K context, $0.06/$0.24
    NLP_MODEL_ID: str = "amazon.nova-lite-v1:0"
    # Nova Lite optimal max; 8K is fine since it doesn't do deep chain-of-thought
    AGENT_MAX_TOKENS: int = 8192
    AGENT_TEMPERATURE: float = 0.1
    AGENT_EVAL_SAMPLE_RATE: float = 0.1
    AGENT_MAX_HISTORY_TURNS: int = 20
    AGENT_REDIS_TTL: int = 604800  # 7 days — active session state TTL
    AGENT_REDIS_KEY_PREFIX: str = "agent:session:"  # Redis key prefix
    RATE_LIMIT_AGENT: str = "30/minute"  # Rate limit for agent chat endpoint
    AGENT_SUMMARY_MODEL_ID: str = "amazon.nova-lite-v1:0"  # Nova Lite — summarization

    # LangSmith — env vars set via .env (read directly by langchain SDK)
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_API_KEY: str = ""  # Required for tracing — set in .env
    LANGCHAIN_PROJECT: str = "stocklens-agent"

    # NLP Cascade OCR
    CASCADE_CONFIDENCE_THRESHOLD: float = 0.7
    CASCADE_OCR_CONFIDENCE_FLOOR: float = 0.6  # escalate if engine read quality is lower
    LLM_MAX_TOKENS: int = 1024
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BACKOFF: float = 1.0  # seconds, doubles each retry
    LLM_CACHE_TTL: int = 86400  # 24 hours
    ENRICH_STATUS_TTL: int = 3600  # 1 hour

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def derive_redis_url(self):
        """Derive REDIS_URL from host/port/password when not set directly.
        Uses rediss:// (TLS) because ElastiCache forces in-transit encryption.
        ponytail: self-signed certs — redis-py handles these by default on rediss://
        """
        if not self.REDIS_URL:
            if self.REDIS_PASSWORD:
                self.REDIS_URL = (
                    f"rediss://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
                )
            else:
                self.REDIS_URL = f"rediss://{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return self


# ── .env guard — fail fast if .env is missing in non-dev environments ──
# Also treat "dev" as a development env (Terraform uses "dev" as env name).

env_path = Path(".env")
_env = os.environ.get("ENVIRONMENT", "development")
if not env_path.exists() and _env not in ("development", "dev", "test"):
    raise RuntimeError(
        f".env file not found at {env_path.resolve()}. "
        "Create one from .env.example or set all env vars directly."
    )

settings = Settings()
