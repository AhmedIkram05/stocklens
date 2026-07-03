# Stage 1: Build dependencies with uv
FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev


# Stage 2: Runtime image
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
