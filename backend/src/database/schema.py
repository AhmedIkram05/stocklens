"""
SQLAlchemy Core ``MetaData`` for Alembic autogeneration **only**.

All runtime queries use raw asyncpg (see ``connection.py``). This module
exists solely so Alembic can detect schema changes when generating
migrations with ``alembic revision --autogenerate``.
"""

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

# ---------------------------------------------------------------------------
# Metadata instance — consumed by Alembic as ``target_metadata``
# ---------------------------------------------------------------------------

target_metadata = MetaData()

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

users = Table(
    "users",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("email", String(255), unique=True, nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("display_name", String(100)),
    Column("is_active", Boolean(), server_default=text("true"), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------

refresh_tokens = Table(
    "refresh_tokens",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("token_hash", String(64), unique=True, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked", Boolean(), server_default=text("false"), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

portfolios = Table(
    "portfolios",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", String(100)),
    Column("description", Text()),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

holdings = Table(
    "holdings",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "portfolio_id",
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ticker", String(10), nullable=False),
    Column("shares", Numeric(18, 6), nullable=False),
    Column("average_cost_basis", Numeric(12, 4), nullable=False),
    Column("currency", String(8), nullable=False, server_default=text("'GBP'")),
    Column("fx_rate_to_gbp", Numeric(18, 10), nullable=False, server_default=text("1.0")),
    Column("average_cost_basis_gbp", Numeric(12, 4), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

transactions = Table(
    "transactions",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "portfolio_id",
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ticker", String(10), nullable=False),
    Column("type", String(4), nullable=False),
    Column("shares", Numeric(18, 6), nullable=False),
    Column("price_per_share", Numeric(12, 4), nullable=False),
    Column("total_amount", Numeric(24, 6), nullable=False),
    Column("currency", String(8), nullable=False, server_default=text("'GBP'")),
    Column("fx_rate_to_gbp", Numeric(18, 10), nullable=False, server_default=text("1.0")),
    Column("total_amount_gbp", Numeric(24, 6), nullable=True),
    Column("transaction_date", Date(), nullable=False),
    Column("notes", Text()),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    CheckConstraint("type IN ('BUY', 'SELL')", name="chk_transactions_type"),
    CheckConstraint("total_amount = shares * price_per_share", name="chk_transactions_amount"),
)

# ---------------------------------------------------------------------------
# Instruments — ticker → (currency, exchange) reference, resolved server-side
# ---------------------------------------------------------------------------

instruments = Table(
    "instruments",
    target_metadata,
    Column("ticker", String(10), primary_key=True),
    Column("currency", String(8), nullable=False, server_default=text("'GBP'")),
    Column("exchange", String(20), nullable=True),
)

# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

receipts = Table(
    "receipts",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("total_amount", Numeric(10, 2)),
    Column("merchant_name", String(255)),
    Column(
        "category_id",
        UUID(as_uuid=True),
        ForeignKey("spending_categories.id", ondelete="SET NULL"),
    ),
    Column("ocr_raw_text", Text()),
    Column("ocr_confidence", REAL()),
    Column("line_items", JSONB()),
    Column("receipt_image_s3_key", String(500)),
    Column("scanned_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# ---------------------------------------------------------------------------
# Spending categories
# ---------------------------------------------------------------------------

spending_categories = Table(
    "spending_categories",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", String(50), unique=True, nullable=False),
    Column("description", String(255)),
    Column("merchant_keywords", JSONB()),
    Column("associated_tickers", JSONB()),
)

# ---------------------------------------------------------------------------
# OHLCV prices
# ---------------------------------------------------------------------------

ohlcv_prices = Table(
    "ohlcv_prices",
    target_metadata,
    Column("id", BigInteger(), primary_key=True, autoincrement=True),
    Column("ticker", String(10), nullable=False),
    Column("date", Date(), nullable=False),
    Column("open", Numeric(12, 4)),
    Column("high", Numeric(12, 4)),
    Column("low", Numeric(12, 4)),
    Column("close", Numeric(12, 4)),
    Column("adjusted_close", Numeric(12, 4)),
    Column("volume", BigInteger()),
)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

model_registry = Table(
    "model_registry",
    target_metadata,
    Column("id", BigInteger(), primary_key=True, autoincrement=True),
    Column("ticker", String(10)),
    Column("mlflow_run_id", String(100)),
    Column("model_version", String(20)),
    Column("alias", String(20)),
    Column("metrics", JSONB()),
    Column("trained_at", DateTime(timezone=True), server_default=func.now()),
)

# ---------------------------------------------------------------------------
# Agent conversations
# ---------------------------------------------------------------------------

agent_conversations = Table(
    "agent_conversations",
    target_metadata,
    Column("id", BigInteger(), primary_key=True, autoincrement=True),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("message", Text()),
    Column("response", Text()),
    Column("tools_used", JSONB()),
    Column("reasoning_steps", JSONB()),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# ---------------------------------------------------------------------------
# Indexes that cannot be expressed as inline column or table constraints
# ---------------------------------------------------------------------------

# Portfolios — user_id lookup
Index("idx_portfolios_user_id", portfolios.c.user_id)

# Holdings — unique per portfolio + ticker
Index("idx_holdings_portfolio_ticker", holdings.c.portfolio_id, holdings.c.ticker, unique=True)

# Transactions — portfolio + date range queries
Index(
    "idx_transactions_portfolio_date",
    transactions.c.portfolio_id,
    transactions.c.transaction_date,
)

# Receipts — user + scanned date
Index("idx_receipts_user_date", receipts.c.user_id, receipts.c.scanned_at)

# OHLCV — unique ticker + date (already enforced by UniqueConstraint but
# Alembic needs the explicit index for autogeneration diffing)
Index("idx_ohlcv_ticker_date", ohlcv_prices.c.ticker, ohlcv_prices.c.date, unique=True)

# Refresh tokens — user lookup
Index("idx_refresh_tokens_user", refresh_tokens.c.user_id)

# Refresh tokens — hash lookup (already unique on column but Alembic
# prefers an explicit index declaration for autogen)
Index("idx_refresh_tokens_hash", refresh_tokens.c.token_hash, unique=True)

# Spending categories — GIN index on merchant_keywords JSONB
Index(
    "idx_categories_keywords",
    spending_categories.c.merchant_keywords,
    postgresql_using="gin",
)

# Agent conversations — user lookup
Index("idx_conversations_user", agent_conversations.c.user_id)

# ---------------------------------------------------------------------------
# prediction_log — stores every prediction request for drift monitoring
# ---------------------------------------------------------------------------

prediction_log = Table(
    "prediction_log",
    target_metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ticker", String(10), nullable=False),
    Column("model_version", String(20), nullable=False),
    Column("prediction", String(4), nullable=False),  # UP/FLAT/DOWN
    Column("confidence", Float, nullable=False),
    Column("probabilities", JSONB, nullable=True),  # {"DOWN": 0.1, "FLAT": 0.3, "UP": 0.6}
    Column("features", JSONB, nullable=True),  # {"window": ..., "stats": ...}
    Column("feature_stats", JSONB, nullable=True),  # {"mean": 0.0, "std": ...}
    Column("raw_feature_names", JSONB, nullable=True),  # ["log_ret_1d", ..., "excess_ret_21d"]
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("idx_prediction_log_ticker_created", prediction_log.c.ticker, prediction_log.c.created_at)
Index("idx_prediction_log_model_version", prediction_log.c.model_version)
Index("idx_prediction_log_created_at", prediction_log.c.created_at)


# ---------------------------------------------------------------------------
# drift_metrics — queryable drift indicators per ticker per feature per run
# ---------------------------------------------------------------------------

drift_metrics = Table(
    "drift_metrics",
    target_metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("drift_run_id", String(36), nullable=False),  # UUID for each drift run
    Column("ticker", String(10), nullable=False),
    Column("model_version", String(20), nullable=False),
    Column("metric_type", String(20), nullable=False),  # 'psi', 'ks_statistic', etc.
    Column("feature_name", String(50), nullable=False),  # 'log_ret_1d', etc.
    Column("drift_score", Float, nullable=False),  # The numeric score
    Column("alert_triggered", Boolean, nullable=False, server_default=text("false")),
    Column("reference_period", String(30), nullable=True),
    Column("current_period", String(30), nullable=True),
    Column("report_s3_key", String(500), nullable=True),
    Column("details", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("idx_drift_metrics_run", drift_metrics.c.drift_run_id)
Index("idx_drift_metrics_ticker_metric", drift_metrics.c.ticker, drift_metrics.c.metric_type)
Index("idx_drift_metrics_alert", drift_metrics.c.alert_triggered)
