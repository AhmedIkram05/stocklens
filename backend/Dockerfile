# Stage 0: Rust native module builder (features-engine)
# Use python:3.12-slim so maturin builds a wheel matching the runtime ABI
# (python:3.12-slim in builder/runtime stages). The official rust image ships
# without Python; installing Python from Debian Bookworm gives us 3.11, which
# produces a cp311-tagged wheel — uninstallable on Python 3.12.
# Cross-compilation is unnecessary: buildx QEMU emulation makes ARM64 look
# native, so the default Rust target is aarch64-unknown-linux-gnu.
FROM python:3.12-slim AS rust-builder

# Build toolchain: C compiler for pyo3/numpy link, pkg-config/libssl for pyo3,
# curl for rustup.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libssl-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Rust via rustup — host is ARM64 under QEMU, so --target is implicit.
ENV CARGO_NET_GIT_FETCH_WITH_CLI=true
RUN curl --retry 3 --retry-delay 5 --connect-timeout 30 \
     --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin via pip (python:3.14-slim ships with pip pre-installed).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install maturin

WORKDIR /src

# Layer A — dependency manifest. Only invalidated when Cargo.toml/Cargo.lock
# change. Cargo validates the lib path exists during manifest parsing, even
# for fetch — so create a dummy lib.rs that Layer B overwrites with the real
# source.
COPY ml/features-engine/Cargo.toml ml/features-engine/pyproject.toml ./
RUN mkdir -p src && touch src/lib.rs
RUN --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/root/.cargo/registry \
    cargo fetch --manifest-path Cargo.toml

# Layer B — real source. Recompiles features-engine only when src changes;
# cached deps + target dir means pyo3/numpy/ndarray aren't recompiled.
COPY ml/features-engine/src ./src
RUN --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/src/target,sharing=locked \
    maturin build --release --features extension --out /wheels


# Stage 1: Python deps via uv.
# uv's cache mount avoids re-downloading 162 deps (~700MB incl. torch/pyarrow)
# on every build. We deliberately DROP UV_COMPILE_BYTECODE here — bytecode
# compilation of 15k files took 13m on ARM64 QEMU. .pyc is generated lazily
# on first import instead; runtime cost is negligible vs build cost.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Install Rust native module into the venv, copy wheel aside for re-install
# in dev/test workflows.
COPY --from=rust-builder /wheels /wheels
RUN uv pip install --no-deps --python /usr/local/bin/python3 /wheels/features_engine*.whl && \
    mkdir -p /app/wheels && \
    cp /wheels/features_engine*.whl /app/wheels/


# Stage 2: Runtime image — install deps directly with pip (no venv, works cross-arch).
FROM python:3.12-slim AS runtime

# apt cache mount reuses downloaded lists between pipeline runs.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        curl \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Non-root for security
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Install Python deps directly into system Python (no venv = cross-arch safe)
COPY --from=builder /app/pyproject.toml /app/uv.lock /app/
COPY --from=builder /app/wheels /app/wheels
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
RUN pip install --no-cache-dir --no-deps /app/wheels/features_engine*.whl && \
    pip install --no-cache-dir -e .

# Copy application code
COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser ml/ ml/
COPY --chown=appuser:appuser docker/ docker/
COPY --chown=appuser:appuser alembic/ alembic/
COPY --chown=appuser:appuser sagemaker/ backend/sagemaker/
COPY --chown=appuser:appuser alembic.ini pyproject.toml uv.lock ./

RUN mkdir -p /model_artifacts/champion && chmod o+rwX /model_artifacts

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "docker/bootstrap.py"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
