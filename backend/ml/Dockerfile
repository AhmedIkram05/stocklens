# Stage 1: Rust native module builder
# Use same Python version as runtime to ensure ABI-compatible wheel (cp314)
FROM python:3.14-slim AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Rust via rustup
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

RUN pip install maturin --no-cache-dir

WORKDIR /src

# Layer 1: Fetch dependencies (only invalidated when Cargo.toml/lock changes).
# Cache mounts persist .cargo/git and .cargo/registry across docker rebuilds.
COPY features-engine/Cargo.toml features-engine/Cargo.lock features-engine/pyproject.toml /src/
# Cargo validates the lib path exists during manifest parsing, even for fetch.
# Dummy placeholder — real src/ overwritten below.
RUN mkdir -p /src/src && touch /src/src/lib.rs
RUN --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/root/.cargo/registry \
    cargo fetch --manifest-path /src/Cargo.toml

# Layer 2: Build with real source (only recompiles our crate on src changes).
# target/ mount preserves incremental compilation artifacts.
COPY features-engine/src /src/src/
RUN --mount=type=cache,target=/src/target,sharing=locked \
    --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/root/.cargo/registry \
    maturin build --release --features extension --out /wheels

# Stage 2: Build Python dependencies with uv
FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

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
RUN groupadd -r mluser && useradd -r -g mluser -u 1000 mluser \
    && chown -R mluser:mluser /app

# Ensure model artifacts directory exists with correct ownership.
# Named volume initialization copies these permissions when the volume is
# first created. If the volume already exists (e.g., from a stale run),
# run `docker compose down -v` to reset it.
RUN mkdir -p /model_artifacts/champion && chown -R mluser:mluser /model_artifacts

USER mluser

# No default CMD - runs via 'docker compose run ml python -m ml.pipeline'
