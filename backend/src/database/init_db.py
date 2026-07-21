"""
Run Alembic migrations at application startup.

Wraps Alembic's ``command.upgrade`` inside ``asyncio.to_thread`` so it can
be called from FastAPI's async lifespan without blocking the event loop.

Also detects and fixes a broken migration state where the database is
stamped at the ``d2f4e1b3c5a7`` identity-bridge revision but the ``0001``
tables never persisted (e.g. because ``spending_categories`` already existed
from a prior migration run, causing a silent transaction rollback).
"""

import asyncio
import logging

import asyncpg
from alembic.command import upgrade
from alembic.config import Config
from sqlalchemy.exc import ProgrammingError

from src.config import settings

logger = logging.getLogger(__name__)

# ── Broken-migration-state fix ─────────────────────────────────────────────
#
# When the database is stuck at the d2f4e1b3c5a7 bridge revision (because
# spending_categories already existed from a prior migration, causing 0001's
# CREATE TABLE to fail and the whole transaction to roll back silently), we
# create ALL tables from the full 0001–0010 chain directly so auth works.
#
# Every statement uses CREATE/INDEX IF NOT EXISTS for idempotency.  The
# trigger function uses CREATE OR REPLACE.
_FIX_SQL = r"""
-- Trigger function (0001)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- 1. users (0001)
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. refresh_tokens (0001)
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. portfolios (0001)
CREATE TABLE IF NOT EXISTS portfolios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(100),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. holdings (0001 + 0008)
CREATE TABLE IF NOT EXISTS holdings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    ticker              VARCHAR(10) NOT NULL,
    shares              NUMERIC(18,6) NOT NULL,
    average_cost_basis  NUMERIC(12,4) NOT NULL,
    currency            VARCHAR(8) NOT NULL DEFAULT 'GBP',
    fx_rate_to_gbp      NUMERIC(18,10) NOT NULL DEFAULT 1.0,
    average_cost_basis_gbp NUMERIC(12,4) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. transactions (0001 + 0008 + 0009)
CREATE TABLE IF NOT EXISTS transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    ticker              VARCHAR(10) NOT NULL,
    type                VARCHAR(4) NOT NULL CHECK (type IN ('BUY','SELL')),
    shares              NUMERIC(18,6) NOT NULL,
    price_per_share     NUMERIC(12,4) NOT NULL,
    total_amount        NUMERIC(24,6) NOT NULL,
    transaction_date    DATE NOT NULL,
    notes               TEXT,
    currency            VARCHAR(8) NOT NULL DEFAULT 'GBP',
    fx_rate_to_gbp      NUMERIC(18,10) NOT NULL DEFAULT 1.0,
    total_amount_gbp    NUMERIC(24,6) NOT NULL DEFAULT 0,
    spending_category_id UUID REFERENCES spending_categories(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6. spending_categories (0001 / af46e8a08234 — already exists on this DB)
CREATE TABLE IF NOT EXISTS spending_categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(50) UNIQUE NOT NULL,
    description     VARCHAR(255),
    merchant_keywords JSONB,
    associated_tickers JSONB
);

-- 7. receipts (0001 + 0002 + 0004 + af46e8a08234)
CREATE TABLE IF NOT EXISTS receipts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_amount        NUMERIC(10,2),
    merchant_name       VARCHAR(255),
    category_id         UUID REFERENCES spending_categories(id) ON DELETE SET NULL,
    ocr_raw_text        TEXT,
    ocr_confidence      REAL,
    line_items          JSONB,
    receipt_image_s3_key VARCHAR(500),
    scanned_at          TIMESTAMPTZ NOT NULL,
    notes               TEXT,
    transaction_date    DATE,
    source              VARCHAR(20) DEFAULT 'regex',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. ohlcv_prices (0001)
CREATE TABLE IF NOT EXISTS ohlcv_prices (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL,
    date            DATE NOT NULL,
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    close           NUMERIC(12,4),
    adjusted_close  NUMERIC(12,4),
    volume          BIGINT
);

-- 9. model_registry (0001)
CREATE TABLE IF NOT EXISTS model_registry (
    id            BIGSERIAL PRIMARY KEY,
    ticker        VARCHAR(10),
    mlflow_run_id VARCHAR(100),
    model_version VARCHAR(20),
    alias         VARCHAR(20),
    metrics       JSONB,
    trained_at    TIMESTAMPTZ DEFAULT now()
);

-- 10. cash_flows (0003)
CREATE TABLE IF NOT EXISTS cash_flows (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    amount       NUMERIC(12,2) NOT NULL,
    source       VARCHAR(50) NOT NULL DEFAULT 'receipt',
    source_id    UUID,
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 11. cascade_decisions (0004)
CREATE TABLE IF NOT EXISTS cascade_decisions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id          UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    raw_text_hash       VARCHAR(16) NOT NULL,
    regex_confidence    REAL NOT NULL,
    llm_confidence      REAL,
    chosen_source       VARCHAR(20) NOT NULL
        CHECK (chosen_source IN ('regex','cascade','pending_llm','degraded','failed')),
    field_confidences   JSONB,
    discrepancies       JSONB,
    processing_time_ms  INTEGER NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 12. prediction_log (0005)
CREATE TABLE IF NOT EXISTS prediction_log (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL,
    model_version   VARCHAR(20) NOT NULL,
    prediction      VARCHAR(4) NOT NULL,
    confidence      FLOAT NOT NULL,
    probabilities   JSONB,
    features        JSONB,
    feature_stats   JSONB,
    raw_feature_names JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 13. drift_metrics (0005 + 0006)
CREATE TABLE IF NOT EXISTS drift_metrics (
    id              BIGSERIAL PRIMARY KEY,
    drift_run_id    VARCHAR(36) NOT NULL,
    ticker          VARCHAR(10) NOT NULL,
    model_version   VARCHAR(20) NOT NULL,
    metric_type     VARCHAR(20) NOT NULL,
    feature_name    VARCHAR(50) NOT NULL,
    drift_score     FLOAT NOT NULL,
    alert_triggered BOOLEAN NOT NULL DEFAULT false,
    reference_period VARCHAR(30),
    current_period  VARCHAR(30),
    report_s3_key   VARCHAR(500),
    details         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 14. instruments (0008)
CREATE TABLE IF NOT EXISTS instruments (
    ticker  VARCHAR(10) PRIMARY KEY,
    currency VARCHAR(8) NOT NULL DEFAULT 'GBP',
    exchange VARCHAR(20)
);

-- 15. conversations (0010)
CREATE TABLE IF NOT EXISTS conversations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title          TEXT,
    message_count  INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 16. agent_conversations (0010 — multi-turn schema)
CREATE TABLE IF NOT EXISTS agent_conversations (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    tools_used      JSONB,
    reasoning_steps JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Indexes (IF NOT EXISTS for idempotency) ──────────────────────────────
CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_holdings_portfolio_ticker ON holdings (portfolio_id, ticker);
CREATE INDEX IF NOT EXISTS idx_transactions_portfolio_date
    ON transactions (portfolio_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_transactions_spending_category
    ON transactions (spending_category_id);
CREATE INDEX IF NOT EXISTS idx_receipts_user_date ON receipts (user_id, scanned_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_prices (ticker, date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_categories_keywords
    ON spending_categories USING gin (merchant_keywords);
CREATE INDEX IF NOT EXISTS idx_cash_flows_portfolio_date ON cash_flows (portfolio_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cascade_decisions_receipt ON cascade_decisions (receipt_id);
CREATE INDEX IF NOT EXISTS idx_cascade_decisions_hash ON cascade_decisions (raw_text_hash);
CREATE INDEX IF NOT EXISTS idx_prediction_log_ticker_created ON prediction_log (ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_prediction_log_model_version ON prediction_log (model_version);
CREATE INDEX IF NOT EXISTS idx_prediction_log_created_at ON prediction_log (created_at);
CREATE INDEX IF NOT EXISTS idx_drift_metrics_run ON drift_metrics (drift_run_id);
CREATE INDEX IF NOT EXISTS idx_drift_metrics_ticker_metric ON drift_metrics (ticker, metric_type);
CREATE INDEX IF NOT EXISTS idx_drift_metrics_alert ON drift_metrics (alert_triggered);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations (user_id);
CREATE INDEX IF NOT EXISTS idx_agent_conversations_cid ON agent_conversations (conversation_id);

-- Unique constraints
ALTER TABLE drift_metrics DROP CONSTRAINT IF EXISTS uq_drift_metrics_run_ticker_metric_feature;
ALTER TABLE drift_metrics ADD CONSTRAINT uq_drift_metrics_run_ticker_metric_feature
    UNIQUE (drift_run_id, ticker, metric_type, feature_name);

-- Row-level triggers (DO block for PG < 14 compatibility)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_updated_at') THEN
        CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_portfolios_updated_at') THEN
        CREATE TRIGGER trg_portfolios_updated_at BEFORE UPDATE ON portfolios
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_holdings_updated_at') THEN
        CREATE TRIGGER trg_holdings_updated_at BEFORE UPDATE ON holdings
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;
"""


async def _detect_and_fix_broken_state() -> None:
    """Check if the database is stuck at the d2f4e1b3c5a7 bridge revision
    and create missing tables directly if so."""
    dsn = _normalise_dsn(settings.DATABASE_URL)
    conn = await asyncpg.connect(dsn)
    try:
        try:
            version = await conn.fetchval("SELECT version_num FROM alembic_version")
        except asyncpg.exceptions.UndefinedTableError:
            # alembic_version table doesn't exist yet — either the DB is
            # brand-new and Alembic hasn't run, or another ECS task is
            # still inside its migration transaction.  Safe to skip.
            return
        if version != "d2f4e1b3c5a7":
            return  # clean state

        users_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
        )
        if users_exists:
            return  # tables already exist despite the bridge stamp

        logger.warning(
            "Broken migration state detected (stuck at d2f4e1b3c5a7, users missing). Fixing..."
        )
        await conn.execute(_FIX_SQL)
        await conn.execute("UPDATE alembic_version SET version_num = '0010'")
        logger.info("Fix applied — created missing tables, stamped alembic_version to 0010")
    finally:
        await conn.close()


def _normalise_dsn(dsn: str) -> str:
    """Strip the +asyncpg driver suffix so asyncpg can parse the URL."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def run_migrations() -> None:
    """Run all pending Alembic migrations.

    Only ignores :class:`ProgrammingError` which occurs when two workers
    race on startup — the second one sees the version table already
    populated and fails harmlessly.  All other errors are propagated so
    CI (and local dev) never silently skips a failed migration.
    """
    alembic_cfg = Config("alembic.ini")
    try:
        await asyncio.to_thread(upgrade, alembic_cfg, "head")
    except ProgrammingError:
        logger.info("Migration already applied by another worker")

    # Post-migration fix: detect broken state (stuck at d2f4e1b3c5a7 bridge
    # revision) and create missing tables directly.
    await _detect_and_fix_broken_state()
