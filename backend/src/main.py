"""
StockLens FastAPI Application.

Phase 1: Backend Foundation + Auth + OCR Migration.
"""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings

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
    # Database pool initialisation and Alembic migrations will be added in Step 2.
    yield
    logger.info("app_shutting_down")
    # Connection pool cleanup will be added in Step 2.


# ── FastAPI application ──

app = FastAPI(
    title="StockLens API",
    description="Receipt OCR → investment analysis → portfolio tracking",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

# CORS — restricted to Expo dev server in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",  # Expo dev server
        "http://localhost:19006",  # Expo web
        "exp://127.0.0.1:19000",  # Expo Go
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health endpoint ──

@app.get("/health", tags=["system"])
async def health():
    """Health check — used by Docker and load balancers."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# ── Router registrations (added in subsequent steps) ──
# from src.auth.router import router as auth_router
# from src.portfolios.router import router as portfolio_router
# from src.holdings.router import router as holding_router
# from src.transactions.router import router as transaction_router
# from src.receipts.router import router as receipt_router
# from src.categories.router import router as category_router
#
# app.include_router(auth_router, prefix="/auth", tags=["auth"])
# app.include_router(portfolio_router, prefix="/portfolios", tags=["portfolios"])
# app.include_router(holding_router, prefix="/portfolios", tags=["holdings"])
# app.include_router(transaction_router, prefix="/portfolios", tags=["transactions"])
# app.include_router(receipt_router, prefix="/receipts", tags=["receipts"])
# app.include_router(category_router, prefix="/categories", tags=["categories"])
