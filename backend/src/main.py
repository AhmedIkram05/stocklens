"""
StockLens FastAPI Application.

Phase 1: Backend Foundation + Auth + OCR Migration.
"""

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
    logger.info("app_starting", environment=settings.ENVIRONMENT)

    # Run pending Alembic migrations at startup so the database schema is
    # always up to date before the first request is served.
    try:
        await run_migrations()
        logger.info("migrations_complete")
    except Exception:
        logger.exception("migrations_failed")
        raise

    # Initialise raw asyncpg connection pool for runtime queries.
    await init_pool(settings.DATABASE_URL)
    logger.info("database_pool_initialised")

    yield

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

# CORS — origins from config (comma-separated, supports dev + production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
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
from src.auth.router import router as auth_router  # noqa: E402
from src.categories.router import router as category_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(receipt_router, prefix="/receipts", tags=["receipts"])
app.include_router(category_router, prefix="/categories", tags=["categories"])
