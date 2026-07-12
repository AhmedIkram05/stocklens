# Stage 0: Rust native module builder (features-engine)
# Use same Python version as runtime to ensure ABI-compatible wheel (cp314)
FROM python:3.14-slim AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    gcc-aarch64-linux-gnu \
    && rm -rf /var/lib/apt/lists/*

# Install Rust via rustup
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

RUN pip install maturin --no-cache-dir

WORKDIR /src
COPY ml/features-engine /src
# Cross-compile for ARM64 (ADR 009) — required for Fargate Graviton runtime.
# Without --target the wheel matches the build host arch and import-crashes.
ENV CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc
RUN maturin build --release --target aarch64-unknown-linux-gnu --features extension --out /wheels


# Stage 1: Build dependencies with uv
FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --index-strategy unsafe-best-match

# Install Rust native module into the virtual environment
COPY --from=rust-builder /wheels /wheels
RUN uv pip install --no-deps /wheels/features_engine*.whl && \
    mkdir -p /app/wheels && \
    cp /wheels/features_engine*.whl /app/wheels/

# Stage 2: Runtime image
FROM python:3.14-slim AS runtime

# Install system deps: tesseract-ocr for pytesseract, libgl for OpenCV, curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (includes pre-installed features_engine)
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy features_engine wheel for re-install after uv sync in dev/test workflows
COPY --from=builder /app/wheels /app/wheels

# Copy uv for dev/test dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY src/ src/
COPY ml/ ml/
COPY docker/ docker/
COPY alembic/ alembic/
COPY alembic.ini pyproject.toml uv.lock ./

# Ensure model artifacts directory exists (for shared volume permissions)
RUN mkdir -p /model_artifacts/champion

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser \
    && chown -R appuser:appuser /app /model_artifacts

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "docker/bootstrap.py"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
