from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens"
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://stocklens:stocklens@postgres_test:5432/stocklens_test"
    )

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    JWT_SECRET_KEY: str  # required, no default
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    BCRYPT_ROUNDS: int = 12

    # AWS
    AWS_REGION: str = "eu-west-2"

    # Bedrock
    BEDROCK_MODEL_ID: str = "anthropic.claude-3-haiku-20240307-v1:0"

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

    # Prediction
    PREDICTION_MODEL_PATH: str = "/model_artifacts/champion/model.pt"
    PREDICTION_CACHE_TTL: int = 21600

    # Prediction Logging / Drift
    PREDICTION_LOG_ENABLED: bool = True
    PREDICTION_LOG_RETENTION_DAYS: int = 90
    DRIFT_ALERT_PSI_THRESHOLD: float = 0.25
    DRIFT_ALERT_KS_THRESHOLD: float = 0.3
    DRIFT_ALERT_JS_THRESHOLD: float = 0.3
    DRIFT_MONITORED_TICKERS: str = ""  # comma-separated, empty = portfolio-only
    DRIFT_REPORT_S3_BUCKET: str = "stocklens-drift-reports"
    DRIFT_REPORT_S3_PREFIX: str = "drift_reports/"

    # NLP Cascade OCR
    CASCADE_CONFIDENCE_THRESHOLD: float = 0.7
    CASCADE_OCR_CONFIDENCE_FLOOR: float = 0.6  # escalate if engine read quality is lower
    LLM_MAX_TOKENS: int = 1024
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BACKOFF: float = 1.0  # seconds, doubles each retry
    LLM_CACHE_TTL: int = 86400  # 24 hours
    ENRICH_STATUS_TTL: int = 3600  # 1 hour

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
