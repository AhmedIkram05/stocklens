"""
StockLens FastAPI Application.

Phase 1: Backend Foundation + Auth + OCR Migration.
"""

import logging
import sys

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler

from src.config import settings
from src.database.connection import close_pool, init_pool
from src.database.init_db import run_migrations
from src.limiter import limiter
from src.receipts.router import router as receipt_router

# ── Structured logging (JSON to stdout, captured by CloudWatch in production) ──

# ponytail: basicConfig ensures structlog/standard-logging messages actually
# appear in CloudWatch. Without it, INFO-level structlog calls are silently
# dropped (root logger defaults to WARNING, no handlers configured).
logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# ── Application lifespan ──


async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    import sys

    print(f"LIFESPAN START: environment={settings.ENVIRONMENT}", file=sys.stderr, flush=True)
    logger.info("app_starting", environment=settings.ENVIRONMENT)

    # Run pending Alembic migrations at startup so the database schema is
    # always up to date before the first request is served.
    try:
        print("LIFESPAN: running migrations...", file=sys.stderr, flush=True)
        await run_migrations()
        print("LIFESPAN: migrations complete", file=sys.stderr, flush=True)
        logger.info("migrations_complete")
    except Exception as e:
        print(f"LIFESPAN ERROR in migrations: {e}", file=sys.stderr, flush=True)
        import traceback

        traceback.print_exc(file=sys.stderr)
        logger.exception("migrations_failed")
        raise

    # Initialise raw asyncpg connection pool for runtime queries.
    print("LIFESPAN: init pool...", file=sys.stderr, flush=True)
    await init_pool(settings.DATABASE_URL)
    print("LIFESPAN: pool initialized", file=sys.stderr, flush=True)
    logger.info("database_pool_initialised")

    # ponytail: try/except wraps the deferred-import zone. The silent exit
    # between "pool initialized" and "yielding..." has no traceback in logs,
    # suggesting either a segfault in a C extension or an exception swallowed
    # by logging config. This wrapper forces the actual error to stderr.
    # If the exit persists, check torch/numpy import-time segfaults.
    try:
        print("LIFESPAN: post-pool init starting...", file=sys.stderr, flush=True)

        # Seed categories on first startup
        from src.categories.seed import seed_categories

        seeded = await seed_categories()
        if seeded:
            logger.info("categories_seeded", count=seeded)
        else:
            print("LIFESPAN: seed_categories returned 0", file=sys.stderr, flush=True)

        # Load prediction model
        from src.prediction.service import prediction_service

        loaded = prediction_service.load_model(settings.PREDICTION_MODEL_PATH)
        if loaded:
            logger.info("prediction_model_loaded", path=settings.PREDICTION_MODEL_PATH)
        else:
            print("LIFESPAN: no champion model, continuing", file=sys.stderr, flush=True)

        # Initialize agent service (warm LangGraph agent — sync compile)
        from src.agent.service import agent_service

        agent_service.initialize()
        logger.info("agent_service_initialised")

        print("LIFESPAN: post-pool init done", file=sys.stderr, flush=True)
    except Exception:
        print("LIFESPAN CRASH:", file=sys.stderr, flush=True)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise

    print("LIFESPAN: yielding...", file=sys.stderr, flush=True)
    try:
        yield
    finally:
        logger.info("app_shutting_down")
        await close_pool()


# ── FastAPI application ──

app = FastAPI(
    title="StockLens API",
    description="Receipt OCR → investment analysis → portfolio tracking",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

# CORS — origins from config (comma-separated, supports dev + production).
# allow_origin_regex catches Expo Go dynamic origins (exp://<lan-ip>:19000
# or exp://<tunnel>.exp.direct:80) that can't be listed statically.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_origin_regex=r"exp://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting — slowapi
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)


# ── Health endpoint ──


@app.get("/health", tags=["system"])
async def health():
    """Health check — used by Docker and load balancers."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# ── Router registrations ──
# Import at function scope to avoid circular imports at module level.
from src.agent.router import router as agent_router  # noqa: E402
from src.agent.tool_endpoints import router as agent_tools_router  # noqa: E402
from src.auth.router import router as auth_router  # noqa: E402
from src.cash_flows.router import router as cash_flows_router  # noqa: E402
from src.categories.router import router as category_router  # noqa: E402
from src.drift.router import router as drift_router  # noqa: E402
from src.holdings.router import router as holdings_router  # noqa: E402
from src.market.router import router as market_router  # noqa: E402
from src.performance.router import router as performance_router  # noqa: E402
from src.portfolios.router import router as portfolio_router  # noqa: E402
from src.prediction.router import router as prediction_router  # noqa: E402
from src.transactions.router import router as transaction_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(receipt_router, prefix="/receipts", tags=["receipts"])
app.include_router(category_router, prefix="/categories", tags=["categories"])
app.include_router(portfolio_router, prefix="/portfolios", tags=["portfolios"])
app.include_router(holdings_router, tags=["holdings"])
app.include_router(market_router, prefix="/market", tags=["market"])
app.include_router(cash_flows_router, tags=["cash_flows"])
app.include_router(performance_router, tags=["performance"])
app.include_router(prediction_router, prefix="/predict", tags=["prediction"])
app.include_router(drift_router, prefix="/drift", tags=["drift"])
app.include_router(transaction_router, tags=["transactions"])
app.include_router(agent_router, prefix="/agent", tags=["agent"])
app.include_router(agent_tools_router, prefix="/agent", tags=["agent"])
