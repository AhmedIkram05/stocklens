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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
