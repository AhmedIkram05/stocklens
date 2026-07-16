# Airflow container for StockLens weekly retraining DAG.
# Uses Python 3.12 (Airflow requires <3.14) with ML deps installed directly.
# Backend source is mounted at runtime so PythonOperator can import
# ml.pipeline, drift modules, etc. — no Docker-in-Docker.
# Multi-stage: rust-builder compiles features_engine (PyO3), final installs wheel.

# Stage 0: Rust native module builder (features_engine)
FROM python:3.12-slim AS rust-builder

# Build toolchain: pkg-config for pyo3/numpy link, libssl for pyo3,
# ca-certificates/curl for rustup. Mirrors the backend Dockerfile's
# proven rust-builder stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libssl-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Rust via rustup
ENV CARGO_NET_GIT_FETCH_WITH_CLI=true
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

RUN pip install maturin --no-cache-dir

WORKDIR /src
# ponytail: single COPY layer (no dep-split like backend). Builds are
# CI-only so layering gains are negligible vs simplicity.
COPY backend/ml/features-engine /src
RUN maturin build --release --features extension --out /wheels

# CI override: --build-context wheel-source=<path> provides pre-built wheel,
# skipping the rust-builder stage entirely (saves ~5min under QEMU).
FROM rust-builder AS wheel-source


# Stage 1: Final Airflow image
FROM python:3.12-slim

ENV AIRFLOW_HOME=/opt/airflow
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps: curl for healthcheck, libgomp for torch parallelism
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install ML dependencies + Airflow + drift deps in one layer.
# pytorch-cpu extra index for CPU-only torch; PyPI for everything else.
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    'torch>=2.12.0' \
    'mlflow>=3.14.0' \
    'scikit-learn>=1.6.0' \
    'numpy>=2.1.0' \
    'pandas>=2.3.0' \
    'matplotlib>=3.10.0' \
    'asyncpg>=0.30.0' \
    'psutil>=6.0.0' \
    'httpx>=0.28.1' \
    'evidently>=0.6.0' \
    'boto3>=1.43.0' \
    'apache-airflow>=3.3.0' \
    'apache-airflow-providers-standard>=1.0.0' \
    'apache-airflow-providers-postgres>=5.0.0' \
    'apache-airflow-providers-fab>=1.0.0' \
    'apache-airflow-providers-amazon>=9.0.0' \
    alembic>=1.15.0

# Install Rust native module (features_engine)
COPY --from=wheel-source /wheels /wheels
RUN pip install --no-deps /wheels/features_engine*.whl

# Copy DAGs, migration helpers, and config
COPY airflow/dags/ /opt/airflow/dags/
COPY airflow/scripts/ /opt/airflow/scripts/
COPY airflow/config/airflow.cfg /opt/airflow/config/

# Backend source for DAG PythonOperator imports (drift.*, src.database.*) + alembic migrations
COPY backend/ /app/

# Airflow env defaults
ENV AIRFLOW__CORE__LOAD_EXAMPLES=False
ENV AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags
ENV AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////opt/airflow/airflow.db
ENV AIRFLOW__SCHEDULER__MIN_FILE_PROCESS_INTERVAL=30

WORKDIR ${AIRFLOW_HOME}

# Backend source code is mounted at runtime via docker-compose volumes
# (not copied into the image) so DAGs can import backend modules directly.

# ponytail: single-container dev setup (scheduler + dag-processor + api-server).
# Phase 5 EC2: split into separate scheduler/dag-processor/api-server/worker containers.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/api/v2/monitor/health || exit 1

# Make init script executable
RUN chmod +x /opt/airflow/scripts/init_airflow_variables.sh

CMD ["bash", "-c", "\
    airflow db migrate \
    && bash /opt/airflow/scripts/init_airflow_variables.sh \
    && airflow dag-processor & \
    airflow scheduler & \
    airflow api-server --port 8080"]
