# Stage 0: Rust native module builder (features-engine)
# Use same Debian base as python:3.14-slim (bookworm/trixie) — required so the
# produced wheel matches the runtime ABI. Cross-compile for ARM64 (ADR 009).
FROM rust:1.83-slim-bookworm AS rust-builder

# Toolchain: gcc-aarch64-linux-gnu for cross-link, pkg-config + libssl for pyo3/pyo3-ffi.
# apt cache mount is reused across pipeline runs (see --mount flags below).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc-aarch64-linux-gnu \
        pkg-config \
        libssl-dev \
        python3-pip \
    && ln -sf /usr/bin/aarch64-linux-gnu-gcc /usr/local/bin/aarch64-unknown-linux-gnu-gcc

# Persist a single cargo target dir across the whole stage. sharing=locked
# is required when --mount is used inside an outer --mount in the same step.
ENV CARGO_NET_GIT_FETCH_WITH_CLI=true \
    CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc

# Install maturin once and cache it; wheels go to /wheels outside the cache
# so the stage export stays small.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir maturin

WORKDIR /src

# Layer A — dependency manifest. Only invalidated when Cargo.toml/Cargo.lock
# change. The dummy lib.rs is required because cargo validates the lib path
# during `cargo fetch`; the real source overwrites it in Layer B.
COPY ml/features-engine/Cargo.toml ml/features-engine/Cargo.lock ./
COPY ml/features-engine/pyproject.toml ./
COPY ml/features-engine/src/lib.rs ./src/lib.rs
RUN mkdir -p src && touch src/lib.rs
RUN --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/src/target,sharing=locked \
    cargo fetch --locked --manifest-path Cargo.toml

# Layer B — real source. Recompiles features-engine only when src changes;
# cached deps + target dir means pyo3/numpy/ndarray aren't recompiled.
COPY ml/features-engine/src ./src
RUN --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/src/target,sharing=locked \
    maturin build --release --target aarch64-unknown-linux-gnu \
        --features extension --out /wheels


# Stage 1: Python deps via uv.
# uv's cache mount avoids re-downloading 162 deps (~700MB incl. torch/pyarrow)
# on every build. We deliberately DROP UV_COMPILE_BYTECODE here — bytecode
# compilation of 15k files took 13m on ARM64 QEMU. .pyc is generated lazily
# on first import instead; runtime cost is negligible vs build cost.
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --index-strategy unsafe-best-match

# Install Rust native module into the venv, copy wheel aside for re-install
# in dev/test workflows.
COPY --from=rust-builder /wheels /wheels
RUN uv pip install --no-deps /wheels/features_engine*.whl && \
    mkdir -p /app/wheels && \
    cp /wheels/features_engine*.whl /app/wheels/


# Stage 2: Runtime image.
FROM python:3.14-slim AS runtime

# apt cache mount reuses downloaded lists between pipeline runs.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# features_engine wheel for re-install after uv sync in dev/test.
COPY --from=builder /app/wheels /app/wheels

# uv for dev/test dep management + uv-python wheeled binary.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY src/ src/
COPY ml/ ml/
COPY docker/ docker/
COPY alembic/ alembic/
COPY alembic.ini pyproject.toml uv.lock ./

RUN mkdir -p /model_artifacts/champion

# Non-root for security.
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser \
    && chown -R appuser:appuser /app /model_artifacts

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "docker/bootstrap.py"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
