# Stage 1: Rust native module builder
FROM rust:1.85-slim-bookworm AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-dev python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv && \
    /venv/bin/pip install maturin

ENV PATH="/venv/bin:$PATH"
WORKDIR /src
COPY features-engine /src
RUN maturin build --release --features extension --out /wheels --interpreter /usr/bin/python3

# Stage 2: Build Python dependencies with uv
FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Install Rust native module into the virtual environment
COPY --from=rust-builder /wheels /wheels
RUN uv pip install --no-deps /wheels/features_engine*.whl

# Stage 3: Runtime image
FROM python:3.14-slim AS runtime

# Install curl for healthcheck, libgomp for torch parallelism
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy uv for dep management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY . /app/ml/

# Non-root user
RUN groupadd -r mluser && useradd -r -g mluser -u 1001 mluser \
    && chown -R mluser:mluser /app

USER mluser

# No default CMD - runs via 'docker compose run ml python -m ml.pipeline'
