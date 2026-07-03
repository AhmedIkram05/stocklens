"""
ML configuration - single source of truth for training and inference settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MLConfig:
    """All ML training and inference configuration."""

    # Sequence settings
    SEQUENCE_LENGTH: int = 30
    N_FEATURES: int = 13  # 13 technical indicators

    # Labeling
    VOL_LOOKBACK: int = 30
    THRESHOLD_MULT: float = 0.5

    # Model architecture
    EMBED_DIM: int = 16
    HIDDEN_DIM: int = 128
    N_LAYERS: int = 2
    DROPOUT: float = 0.3
    N_CLASSES: int = 3  # DOWN, FLAT, UP

    # Training
    EPOCHS: int = 100
    BATCH_SIZE: int = 64
    LEARNING_RATE: float = 1e-3
    WEIGHT_DECAY: float = 1e-5
    PATIENCE: int = 10  # early stopping patience
    MIN_DELTA: float = 1e-4  # minimum validation loss improvement

    # Split
    TRAIN_SPLIT: float = 0.7
    VAL_SPLIT: float = 0.15
    TEST_SPLIT: float = 0.15

    # Data
    TRAINING_TICKERS: list[str] = field(
        default_factory=lambda: [
            "AAPL",
            "MSFT",
            "GOOGL",
            "AMZN",
            "NVDA",
            "META",
            "TSLA",
            "JPM",
            "V",
            "UNH",
            "XOM",
            "JNJ",
            "WMT",
            "PG",
            "MA",
            "CVX",
            "HD",
            "MRK",
            "ABBV",
            "KO",
            "PEP",
            "AVGO",
            "COST",
            "CRM",
            "BAC",
            "TMO",
            "MCD",
            "ABT",
            "ACN",
            "DIS",
            "DHR",
            "LIN",
            "NFLX",
            "CSCO",
            "ADBE",
            "NEE",
            "CMCSA",
            "PFE",
            "TXN",
            "BMY",
            "AMGN",
            "PM",
            "QCOM",
            "RTX",
            "IBM",
            "HON",
            "CAT",
            "INTU",
            "AMAT",
            "AMT",
            "MS",
            "PLD",
            "SBUX",
            "VZ",
            "GE",
        ]
    )
    OHLCV_YEARS: int = 5  # How many years of history to fetch

    # Paths
    MODEL_ARTIFACT_DIR: str = field(
        default_factory=lambda: os.environ.get("MODEL_ARTIFACT_DIR", "/model_artifacts/champion")
    )
    MLFLOW_TRACKING_URI: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    )
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens"
        )
    )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Return a sync psycopg2-compatible DSN for pandas.read_sql.

        Strips the ``+asyncpg`` suffix from the async DSN.
        """
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

    # Inference
    MIN_OHLCV_DAYS: int = 60  # Minimum days needed for feature computation (30 window + padding)
    PREDICTION_CACHE_TTL: int = 21600  # 6 hours in seconds

    # Class names
    CLASS_NAMES: tuple[str, ...] = ("DOWN", "FLAT", "UP")


ML_CONFIG = MLConfig()
