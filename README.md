# StockLens

> Scan receipts → trade stocks with your spending → track portfolios with LSTM forecasts & AI agent. Built with FastAPI, PyTorch, LangGraph, Rust, Terraform.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&labelColor=000000&logo=python" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&labelColor=000000&logo=fastapi" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&labelColor=000000&logo=typescript" alt="TypeScript"/>
  <img src="https://img.shields.io/badge/React_Native-61DAFB?style=for-the-badge&labelColor=000000&logo=react" alt="React Native"/>
  <img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&labelColor=000000&logo=rust" alt="Rust"/>
  <img src="https://img.shields.io/badge/LangGraph-7C3AED?style=for-the-badge&labelColor=000000" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&labelColor=000000&logo=pytorch" alt="PyTorch"/>
  <br/>
  <img src="https://img.shields.io/badge/AWS-232F3E?style=for-the-badge&labelColor=000000&logo=amazonwebservices" alt="AWS"/>
  <img src="https://img.shields.io/badge/Terraform-844FBA?style=for-the-badge&labelColor=000000&logo=terraform" alt="Terraform"/>
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&labelColor=000000&logo=docker" alt="Docker"/>
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&labelColor=000000&logo=postgresql" alt="PostgreSQL"/>
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&labelColor=000000&logo=redis" alt="Redis"/>
  <img src="https://img.shields.io/badge/Airflow-017CEE?style=for-the-badge&labelColor=000000&logo=apacheairflow" alt="Airflow"/>
  <img src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&labelColor=000000&logo=githubactions" alt="GitHub Actions"/>
  <br/>
  <img src="https://img.shields.io/badge/MLflow-0194E2?style=for-the-badge&labelColor=000000&logo=mlflow" alt="MLflow"/>
  <img src="https://img.shields.io/badge/Optuna-F97316?style=for-the-badge&labelColor=000000" alt="Optuna"/>
  <img src="https://img.shields.io/badge/Expo-54-000020?style=for-the-badge&labelColor=000000&logo=expo" alt="Expo"/>
</p>

<p align="center">
  <a href="https://github.com/AhmedIkram05/stocklens/actions/workflows/ci.yml">
    <img src="https://github.com/AhmedIkram05/stocklens/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://github.com/AhmedIkram05/stocklens/actions/workflows/codeql.yml">
    <img src="https://github.com/AhmedIkram05/stocklens/actions/workflows/codeql.yml/badge.svg" alt="CodeQL">
  </a>
  <a href="https://codecov.io/gh/AhmedIkram05/stocklens">
    <img src="https://codecov.io/gh/AhmedIkram05/stocklens/branch/main/graph/badge.svg" alt="Codecov">
  </a>
</p>

<br/>

<details>
<summary><strong>Table of Contents</strong> (click to expand)</summary>

- [Why StockLens](#why-stocklens)
- [Architecture Overview](#architecture-overview)
- [Engineering Highlights](#engineering-highlights)
- [Key Metrics at a Glance](#key-metrics-at-a-glance)
- [Demos](#demos)
- [Deep Dives](#deep-dives)
  - [LangGraph Conversational Agent](#-langgraph-conversational-agent)
  - [LSTM Directional Forecasting](#-lstm-directional-forecasting)
  - [NLP Cascade OCR Pipeline](#-nlp-cascade-ocr-pipeline)
  - [Rust Features Engine](#-rust-features-engine)
  - [Portfolio Analytics](#-portfolio-analytics)
  - [MLOps & Retraining Pipeline](#-mlops--retraining-pipeline)
- [Design Decisions](#design-decisions)
- [Testing Strategy](#testing-strategy)
- [Infrastructure (Terraform)](#infrastructure-terraform)
- [CI/CD Pipeline](#cicd-pipeline)
- [Security Model](#security-model)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Related Projects](#related-projects)

</details>

---

## Why StockLens

StockLens turns your spending into stock trades. Scan a receipt, the OCR cascade extracts the total, and you can buy or sell real stocks in real time with that amount. Build portfolios tracked with cash-flow-aware time-weighted return, get LSTM-powered 5-day directional forecasts, compare your performance against SPY (tracking error + information ratio), and ask an AI agent natural-language questions about your holdings.

Beneath the mobile app is a production-grade system: a **Rust/PyO3 features engine** replaces pandas for zero-cost technical indicator computation, a **LangGraph 2-node ReAct agent** with 16 tools communicates via AWS Bedrock Converse, a **confidence-gated OCR cascade** escalates from Tesseract regex to Bedrock Vision LLM only when accuracy demands it, and a weekly **Airflow MLOps pipeline** retrains the LSTM with automated champion/challenger promotion and Evidently drift detection. All deployed via **Terraform on AWS ECS Fargate ARM64/Graviton** with GitHub Actions OIDC CI/CD.

| Layer                 | Implementation                                                                                       | Scale                                                             |
| --------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **Frontend**          | React Native (TypeScript 5.9, Expo 54, React 19) with dark mode, biometric auth, real-time portfolio | 85 test files, 822 assertions                                     |
| **Backend API**       | FastAPI (Python 3.13) — asyncpg, SQLAlchemy 2.0, Pydantic v2, structlog, slowapi rate limiting       | 76 test files, 1,415 test functions, 90% cov gate                 |
| **Rust Acceleration** | PyO3/Maturin native extension replacing pandas-based technical indicators                            | 13 source modules, 12 exported functions, zero-cost abstractions  |
| **ML Model**          | PyTorch Global LSTM with entity embeddings + Optuna HPO (50 trials)                                  | 17 features, 55–475+ tickers, 6yr OHLCV lookback                  |
| **LLM Agent**         | LangGraph ReAct (2-node `StateGraph`, 16 tools) via AWS Bedrock Converse API                         | SSE streaming, two-tier Redis+RDS persistence                     |
| **NLP Pipeline**      | OCR cascade: Tesseract regex → heuristic scoring → Bedrock Vision LLM → fallback                     | rapidfuzz merchant matching, discrepancy detection, Redis caching |
| **MLOps**             | Airflow weekly retraining, Evidently AI drift detection, champion/challenger auto-promotion          | PSI/KS/JSD thresholds, MLflow tracking, S3 delivery               |
| **Infrastructure**    | Terraform IaC (≥1.9) on AWS ECS Fargate ARM64/Graviton                                               | Multi-AZ RDS, ElastiCache Redis 8.8, WAF, Auto Scaling            |
| **CI/CD**             | GitHub Actions OIDC — 9 CI jobs + 7-stage deploy pipeline                                            | Codecov, Checkov, tfsec, Gitleaks, Trivy, hadolint                |

---

## Architecture Overview

The system runs entirely on AWS with a VPC-isolated topology: public subnets contain the Application Load Balancer (WAF-protected), private subnets host ECS Fargate ARM64 tasks, Multi-AZ RDS PostgreSQL, and ElastiCache Redis. The MLOps layer runs on a separate ECS cluster with Airflow orchestration, MLflow tracking on Fargate, and SageMaker as an optional serving backend.

```mermaid
flowchart TB
    subgraph Client["Mobile Client"]
        RN[React Native<br/>TypeScript + Expo]
    end

    subgraph AWS["AWS Cloud — eu-west-2"]
        subgraph Public["Public Subnets"]
            ALB[Application<br/>Load Balancer]
            WAF[AWS WAF<br/>Rate-based + OWASP]
        end

        subgraph Private["Private Subnets"]
            subgraph ECS_API["ECS Fargate ARM64"]
                API[FastAPI Backend<br/>uvicorn workers]
            end

            subgraph ECS_AGENT["ECS Fargate ARM64"]
                AGENT[LangGraph Agent<br/>ChatBedrockConverse]
            end

            RDS[(RDS PostgreSQL<br/>Multi-AZ<br/>db.t4g.micro)]
            RC[(ElastiCache Redis<br/>cache.r6g.micro<br/>TLS + AUTH)]

            subgraph ECS_ML["ECS Fargate ARM64"]
                AF[Airflow<br/>Weekly Retraining]
                MLF[MLflow<br/>Experiment Tracking]
            end
        end

        BEDROCK[AWS Bedrock<br/>Nova Lite Converse]
        S3_BUCKETS[(S3 Buckets<br/>MLflow Artifacts<br/>Drift Reports<br/>Champion Model<br/>CloudFront)]
        CW[CloudWatch<br/>Logs + Metrics + Alarms]

        subgraph EFS["EFS"]
            CHAMPION[(Champion<br/>model.pt)]
        end

        SM[SageMaker<br/>ml.m5.xlarge]
    end

    subgraph CI_CD["CI/CD — GitHub Actions"]
        GHA[9 CI Jobs<br/>Lint / TS / Tests / Rust /<br/>Docker / IaC / Secrets]
        CD[7-Stage Deploy<br/>Build → Push → Scan →<br/>Plan → Review → Apply]
        TF[Terraform<br/>S3 State + DynamoDB Lock]
    end

    RN -->|HTTPS| WAF
    WAF --> ALB
    ALB --> API
    API --> RDS
    API --> RC
    API --> S3_BUCKETS
    API -.-> BEDROCK
    AGENT --> BEDROCK
    API --> CW
    AGENT --> RC
    AGENT --> RDS
    AF --> MLF
    AF --> S3_BUCKETS
    AF --> RDS
    API --> CHAMPION
    SM --> CHAMPION
    API -.-> SM

    CI_CD --> ECS_API
    CI_CD --> ECS_ML
    CI_CD --> TF

    style Client fill:#2d2d2d,color:#fff,stroke:#555
    style AWS fill:#1a1a2e,color:#fff,stroke:#334
    style Public fill:#1a2a1a,color:#fff
    style Private fill:#1a1a2e,color:#fff
    style CI_CD fill:#2d1b1b,color:#fff,stroke:#553
```

**End-to-end flow:** A user scans a receipt → the OCR cascade extracts the total (Tesseract → Bedrock Vision LLM fallback) → the user confirms and trades that exact amount → the transaction is recorded with a cash-flow entry → portfolio analytics compute time-weighted return with explicit cash-flow handling → the LSTM model forecasts 5-day direction for each holding → the LangGraph agent answers questions by calling 16 tools (portfolio, performance, market data, spending, forecasts) via SSE streaming.

---

## Engineering Highlights

| Area                      | Decision                                                                                | Why                                                                                                                                                                                                                                                       |
| ------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Container strategy**    | Multi-stage Docker builds for all 4 services (Backend, Airflow, ML Training, SageMaker) | Backend: `python:3.13-slim` build stage with maturin compiles Rust wheel → runtime copies only `.so`. ARM64 cross-build via Buildx. Image ~450MB vs ~1.2GB naive.                                                                                         |
| **Compose architecture**  | Separated infra (Postgres, Redis) from app (Backend + Agent) via profiles               | Start DB alone for host-based dev (`docker compose -f postgres.yml up`), or full stack with `-f postgres.yml -f app.yml`. Standard Docker composition pattern.                                                                                            |
| **CI pipeline**           | 9 parallel jobs, path-aware execution                                                   | Lint (ruff + ESLint + prettier), TypeScript, Frontend Tests (Jest), Security Audit, Rust (clippy + cargo test), Backend Tests (pytest + 90% cov), Docker Validation, IaC (Checkov + tfsec), Secrets (Gitleaks). Each job runs only when its paths change. |
| **CI caching**            | Docker layer caching + pip/npm dependency caching                                       | Docker builds use `type=gha` cache (GitHub Actions cache layer sharing). Python pip and npm `node_modules` cached via `actions/setup-python` / `setup-node`.                                                                                              |
| **Agent architecture**    | Manual LangGraph `StateGraph` (no `create_react_agent`) with two-tier history           | Explicit control over agentic loop; manual history management enables two-tier Redis (7-day TTL) + PostgreSQL persistence surviving server restarts without context loss.                                                                                 |
| **ML feature compute**    | Rust/PyO3 native extension replacing pandas                                             | 12 exported functions compute 17 features (14 technical + 3 cross-sectional) at O(n) with zero Python overhead. Called from Airflow DAG and inference endpoint.                                                                                           |
| **Deployment gating**     | Backend health check → Frontend deploy (via ECS service ordering)                       | Pipeline explicitly waits for ECS rolling update to pass health checks before considering deploy complete. Zero API/UI version mismatch in production.                                                                                                    |
| **Network isolation**     | Three-tier security groups                                                              | Internet → ALB (443) → ECS (8000) → RDS (5432)/Redis (6379). No public database, no direct ECS access.                                                                                                                                                    |
| **Frontend proxy**        | N/A (Expo/React Native) — API calls direct to ALB via `EXPO_PUBLIC_API_URL`             | Same binary works in dev (localhost) and prod (ALB DNS) — `EXPO_PUBLIC_API_URL` injected at build time.                                                                                                                                                   |
| **CI/CD auth**            | OIDC federation with AWS — no long-lived credentials                                    | IAM role assumed per-run, scoped to `main` branch only. Zero AWS secrets stored in GitHub.                                                                                                                                                                |
| **MLOps drift detection** | Evidently AI PSI/KS/JSD on features + predictions                                       | Lightweight, Airflow-native, covers distribution, feature, and model drift in one library. Reports stored to S3, alerts via CloudWatch.                                                                                                                   |

---

## Key Metrics at a Glance

| Category           | Metric                        | Value                                                  |
| ------------------ | ----------------------------- | ------------------------------------------------------ |
| **API**            | REST endpoints                | 59 across 14 routers                                   |
| **Tests**          | Backend test files            | 76                                                     |
|                    | Backend test functions        | 1,415                                                  |
|                    | Frontend test files           | 85                                                     |
|                    | Frontend assertions           | 822                                                    |
|                    | Coverage gate (backend)       | 90% line                                               |
|                    | Coverage gate (frontend)      | branches≥75%, func≥80%, lines≥90%                      |
| **Infrastructure** | Terraform modules             | 14                                                     |
|                    | Terraform resources           | 193                                                    |
|                    | Docker services (dev)         | 7 core (+ test profiles)                               |
| **MLOps**          | LSTM features                 | 17 (14 technical + 3 cross-sectional)                  |
|                    | LSTM architecture             | 2 layers, hidden=80, dropout=0.535                     |
|                    | Optuna HPO trials             | 50                                                     |
|                    | Tickers (dev / full)          | 55 / 475                                               |
|                    | Agent tools                   | 16 across 7 categories                                 |
| **CI/CD**          | Parallel CI jobs              | 9                                                      |
|                    | CD pipeline stages            | 7                                                      |
|                    | Security scanners             | 6 (Codecov, Checkov, tfsec, Gitleaks, Trivy, hadolint) |
| **Documentation**  | Architecture Decision Records | 9                                                      |
|                    | Deep-dive components          | 6                                                      |
|                    | Demo assets                   | 15 (6 MOV, 6 MP4, 3 PNG)                               |
| **Runtime**        | Python version                | 3.13                                                   |
|                    | Rust toolchain                | PyO3 0.29, Maturin 1.14                                |
|                    | PostgreSQL                    | 18 (Alpine)                                            |
|                    | Redis                         | 8.8 (Alpine)                                           |

---

## Demos

### Mobile App — Core User Flows

The React Native app walkthroughs showing receipt-to-trade flow, portfolio tracking, and auth.

| Demo                                                                         | Description                                                                                                                                                       |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ![Receipt Scanning](assets/demos/demo-scanning_2_receipts_success.mp4)       | **Receipt scanning**: two receipts processed through the OCR cascade (Tesseract → Bedrock Vision LLM fallback), totals extracted, merchant matched via rapidfuzz. |
| ![Portfolio Screens](assets/demos/demo-portfolios_screens.mp4)               | **Portfolio screens**: holdings view, sector exposure, performance vs SPY (tracking error + information ratio), cash-flow-aware TWR calculation.                  |
| ![Auth Flow](assets/demos/demo-signup_login_dark_mode_empty_home_screen.mp4) | **Auth flow**: signup → login → biometric prompt → dark mode toggle → empty home state (no portfolios yet).                                                       |
| ![Home Screens](assets/demos/demo-summary_and_populated_home_screens.mp4)    | **Home screen populated**: portfolio summary cards, recent transactions, spending analysis, LSTM forecast chips.                                                  |
| ![Auto-lock](assets/demos/demo-auto_lock.mp4)                                | **Auto-lock after backgrounding**: biometric re-authentication required to resume, session restored seamlessly.                                                   |

### AI Agent & MLOps

| Demo                                                                 | Description                                                                                                                                                                                                                                                |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ![Agent Interaction](assets/demos/demo-agent_screen_features.mp4)    | **Full agent interaction**: natural-language query → tool calls (16 tools across 7 categories) → SSE streaming response with progressive rendering.                                                                                                        |
| ![Agent Eval in CI](assets/demos/agent_eval_GHactions.mov)           | **Agent evaluation in CI**: correctness judged by GLM-4.7-Flash, LangSmith tracing at 10% sample rate.                                                                                                                                                     |
| ![LangSmith UI](assets/demos/langsmith.mp4)                          | **LangSmith UI walkthrough**: traces, runs, evaluation results, and prompt playground for the LangGraph agent.                                                                                                                                             |
| ![Airflow DAG](assets/demos/airflow_dag_weekly_retraining-graph.png) | **Airflow DAG**: weekly retraining (Monday 06:00 UTC) → feature computation (Rust engine) → Optuna HPO (50 trials) → champion/challenger evaluation (DA improvement > 2pp) → Evidently drift detection (PSI/KS/JSD) → EFS + S3 + model_registry promotion. |
| ![MLflow Training](assets/demos/mlflow.mov)                          | **MLflow UI**: experiment tracking with Optuna hyperparameters logged, loss curves, evaluation metrics, model artifacts registered.                                                                                                                        |

### Infrastructure & CI/CD

| Demo                                                 | Description                                                                                                                                                                  |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ![9 Parallel CI Jobs](assets/demos/ci_GHactions.mov) | **GitHub Actions CI**: 9 parallel jobs (Lint, TypeScript, Frontend Tests, Security Audit, Rust, Backend Tests, Docker, IaC, Secrets) — all must pass.                        |
| ![7-Stage Deploy](assets/demos/deploy_GHactions.mov) | **CD pipeline**: Build (Rust wheel ARM64, 4 Docker images) → Trivy scan (critical only) → Terraform plan → Manual approval → Terraform apply → ECS rolling update.           |
| ![AWS Infra Walkthrough](assets/demos/aws_infra.mp4) | **AWS Console walkthrough**: VPC (2 AZs, public/private), ECS Fargate ARM64 services, Multi-AZ RDS, ElastiCache Redis, WAF, CloudWatch alarms, EFS mount for champion model. |

### Backend & Frontend Test Results

| Backend Tests                                               | Frontend Tests                                                           |
| ----------------------------------------------------------- | ------------------------------------------------------------------------ |
| ![Backend Tests](assets/demos/backend-tests.png)            | ![Frontend Tests](assets/demos/frontend-tests.png)                       |
| 1,415 tests passing, 90% line coverage gate enforced in CI. | 822 assertions, coverage gates (branches≥75%, functions≥80%, lines≥90%). |

---

## Deep Dives

---

### LangGraph Conversational Agent

A **2-node ReAct agent** built with LangGraph's `StateGraph` — not the `create_react_agent` convenience wrapper — giving explicit control over the reasoning loop. Chat history uses **manual two-tier persistence**: Redis for active session state (7-day TTL) and PostgreSQL for durable cross-session history.

**Agent architecture:**

```mermaid
flowchart LR
    USER((User)) -->|SSE Stream| API[FastAPI<br/>SSE Endpoint]
    API -->|Load History| RDS[(PostgreSQL<br/>History)]
    API -->|Active State| RC[(Redis<br/>7d TTL)]
    API --> AGENT[StateGraph Agent Node]
    AGENT -->|ChatBedrockConverse| BEDROCK[AWS Bedrock<br/>Amazon Nova Lite]
    AGENT -->|Tool Calls| TN[ToolNode]

    subgraph Tools["16 Tools — 7 Categories"]
        P1[get_portfolio_summary]
        P2[get_portfolio_holdings]
        P3[get_sector_exposure]
        PE1[get_portfolio_performance]
        PE2[compare_to_benchmark]
        A1[get_portfolio_diversification]
        A2[compare_tickers_side_by_side]
        M1[get_market_ohlcv]
        M2[get_market_quote]
        M3[get_ticker_info]
        M4[get_market_news]
        F1[get_lstm_forecast]
        S1[get_spending_analysis]
        S2[get_recent_transactions]
        S3[get_cash_flow_summary]
        I1[get_dividend_insights]
    end

    TN --> Tools
    TN -->|Response| AGENT

    classDef model fill:#4a1a7a,color:#fff
    class BEDROCK model
```

**Configuration:**

| Parameter                | Value                                                     | Notes                                                                                             |
| ------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Framework                | LangGraph `StateGraph` (manual, no checkpointer)          | Explicit control over agentic loop                                                                |
| LLM                      | ChatBedrockConverse — defaults to `amazon.nova-lite-v1:0` | Configurable via `BEDROCK_MODEL_ID` env var                                                       |
| Tools registered         | 16 across 7 categories                                    | Portfolio(3) + Performance(2) + Analysis(2) + Market(4) + Forecast(1) + Spending(3) + Insights(1) |
| Conversation persistence | Two-tier: Redis (7-day TTL) + PostgreSQL                  | Survives server restarts without context loss                                                     |
| Streaming                | SSE via `astream_events`                                  | Progressive UI rendering                                                                          |
| Judge / eval             | `zai.glm-4.7-flash`                                       | Correctness evaluation; LangSmith tracing at 10% sample rate                                      |
| Rate limiting            | 30 requests/minute                                        | On the agent endpoint                                                                             |
| History                  | Max 20 conversation turns per session                     | Keeps context windows manageable                                                                  |

**Registered tools:**

| Category    | Tools                                                                        | Count |
| ----------- | ---------------------------------------------------------------------------- | ----- |
| Portfolio   | `get_portfolio_summary`, `get_portfolio_holdings`, `get_sector_exposure`     | 3     |
| Performance | `get_portfolio_performance`, `compare_to_benchmark`                          | 2     |
| Analysis    | `get_portfolio_diversification_score`, `compare_tickers_side_by_side`        | 2     |
| Market Data | `get_market_ohlcv`, `get_market_quote`, `get_ticker_info`, `get_market_news` | 4     |
| Forecasting | `get_lstm_forecast`                                                          | 1     |
| Spending    | `get_spending_analysis`, `get_recent_transactions`, `get_cash_flow_summary`  | 3     |
| Insights    | `get_dividend_insights`                                                      | 1     |

The agent is invoked **server-side with full history reconstruction**: on each request, the API loads conversation history from PostgreSQL, hydrates Redis with active session state, and passes the full message list into the graph.

---

### LSTM Directional Forecasting

A **Global LSTM** model forecasting directional price movement (DOWN / FLAT / UP) over a 5-day horizon using 17 technical features computed across the entire S&P 500 universe. The "global" architecture shares a single LSTM backbone across all tickers while learning per-ticker identity via **entity embeddings** (16-dim).

**Model architecture:**

```mermaid
flowchart LR
    subgraph Input["Input (30-day window)"]
        OHLCV[(OHLCV<br/>Close/High/Low/Vol)]
    end

    subgraph FE["Rust Features Engine<br/>(PyO3 native)"]
        LR[Log Returns<br/>1/5/10/20d]
        MA[Moving Averages<br/>SMA-3/5/10/20]
        RSI[RSI-14]
        MACD[MACD<br/>12/26/9]
        RV[Rolling Vol<br/>20d]
        VR[Vol Rank<br/>20d]
        BB[Bollinger<br/>20/2.0]
        ATR[ATR-14]
        OBV[OBV]
        WR[Williams %R-14]
        ROC[ROC-10]
    end

    subgraph XS["Cross-Sectional vs SPY"]
        XR[Excess Return<br/>1/5/20d]
    end

    subgraph Model["Global LSTM"]
        EMB[Embedding<br/>dim=16]
        LSTM1[LSTM Layer 1<br/>hidden=80]
        LSTM2[LSTM Layer 2<br/>hidden=80]
        DO[Dropout p=0.535]
        FC[Linear<br/>160→3]
    end

    subgraph Loss["Loss & Optimization"]
        FL[Focal Loss<br/>γ=1.49]
        OPT[AdamW<br/>lr=3.14e-4<br/>wd=2.06e-4]
    end

    OHLCV --> FE
    OHLCV --> XS
    FE --> Model
    XS --> Model
    TICKER[Ticker ID] --> EMB
    EMB --> LSTM1
    LSTM1 --> LSTM2
    LSTM2 --> DO --> FC
    FC -->|3-class| FL
    FL --> OPT
```

**Training configuration (from `ml/config.py`):**

| Hyperparameter       | Value           | Optuna Search Space                             | Source                    |
| -------------------- | --------------- | ----------------------------------------------- | ------------------------- |
| Sequence length      | 30 trading days | —                                               | Fixed                     |
| Forecast horizon     | 5 trading days  | —                                               | Fixed                     |
| Embedding dimension  | 16              | —                                               | HPO best                  |
| Hidden dimension     | **80**          | 32 → 128                                        | Optuna best (Trial 14)    |
| LSTM layers          | 2               | —                                               | Fixed (unidirectional)    |
| Dropout              | **0.535**       | 0.1 → 0.7                                       | Optuna best               |
| Focal loss gamma     | **1.49**        | 0.5 → 4.0                                       | Optuna best               |
| Learning rate        | **3.14e-4**     | 1e-5 → 1e-3                                     | Optuna best               |
| Weight decay         | **2.06e-4**     | 1e-5 → 1e-3                                     | Optuna best               |
| Threshold multiplier | 1.0             | Phase 2 HPO best (test_dir=51.63%)              | HPO best                  |
| Batch size           | 256             | —                                               | Fixed (MPS GPU efficient) |
| Features             | 17              | 14 technical + 3 cross-sectional excess returns | Fixed                     |
| Classes              | 3               | DOWN / FLAT / UP                                | Fixed                     |
| Tickers (dev)        | 55+             | S&P 500 subset                                  | Configurable              |
| Tickers (full)       | 475+            | Full S&P 500                                    | Configurable              |
| OHLCV lookback       | 6 years         | —                                               | Fixed                     |
| Train / Val / Test   | 70 / 15 / 15    | Chronological (no future leakage)               | Fixed                     |
| Epochs               | 100             | —                                               | Training config           |

**Performance metrics (from Optuna trials, config comments):**

| Metric                   | Range           | Best Trial  | Baseline             |
| ------------------------ | --------------- | ----------- | -------------------- |
| Directional Accuracy     | 49.78% – 51.63% | 51.63%      | 33% (majority-class) |
| Simulated Sharpe Ratio   | 0.67 – 0.97     | 0.97        | 0.0 (random)         |
| Best validation accuracy | 55.27%          | Trial 14/50 | —                    |

> **Context:** Predicting 3-class directional movement over a 5-day window in highly stochastic markets. The model's 50-52% accuracy is a **50%+ improvement over the 33% random baseline**. The simulated Sharpe of 0.97 reflects risk-adjusted return in a zero-cost trading simulation.

**17 features in detail:**

| #   | Feature             | Computation                                   | Domain |
| --- | ------------------- | --------------------------------------------- | ------ |
| 1   | `log_return_1d`     | log(close<sub>t</sub> / close<sub>t-1</sub>)  | Rust   |
| 2   | `log_return_5d`     | log(close<sub>t</sub> / close<sub>t-5</sub>)  | Rust   |
| 3   | `log_return_10d`    | log(close<sub>t</sub> / close<sub>t-10</sub>) | Rust   |
| 4   | `log_return_20d`    | log(close<sub>t</sub> / close<sub>t-20</sub>) | Rust   |
| 5   | `sma_3`             | 3-day simple moving average                   | Rust   |
| 6   | `sma_5`             | 5-day simple moving average                   | Rust   |
| 7   | `sma_10`            | 10-day simple moving average                  | Rust   |
| 8   | `sma_20`            | 20-day simple moving average                  | Rust   |
| 9   | `rsi_14`            | 14-day Relative Strength Index (Wilder's)     | Rust   |
| 10  | `macd`              | MACD line (12/26/9 EMA)                       | Rust   |
| 11  | `rolling_vol_20`    | 20-day rolling standard deviation             | Rust   |
| 12  | `vol_rank_20`       | 20-day rolling percentile rank                | Rust   |
| 13  | `bollinger_pct`     | Bollinger %B (20-period, 2.0 std)             | Rust   |
| 14  | `volume_pct`        | Volume % change vs. 20-day avg                | Python |
| 15  | `excess_return_1d`  | 1-day cross-sectional excess vs. SPY          | Python |
| 16  | `excess_return_5d`  | 5-day cross-sectional excess vs. SPY          | Python |
| 17  | `excess_return_20d` | 20-day cross-sectional excess vs. SPY         | Python |

---

### NLP Cascade OCR Pipeline

A **confidence-gated cascade** that progressively escalates to more expensive models only when accuracy warrants it. At the base: Tesseract-based regex extraction. If confidence is insufficient (overall < 0.7, OCR < 0.6, unverified merchant, or reconciliation mismatch), it escalates through Bedrock Vision LLM, then text-only LLM, and finally a degraded fallback.

**Pipeline flow:**

```mermaid
flowchart TB
    subgraph Capture["Receipt Image"]
        IMG[(Camera / Gallery<br/>JPEG/PNG)]
    end

    subgraph Tesseract["Stage 1: Tesseract OCR"]
        TESS[ThreadPoolExecutor<br/>3 workers]
        RE[Regex Extraction<br/>total/merchant/date/items]
        SCORE[Heuristic Scoring<br/>total=0.88, merchant=0.90<br/>date=0.85, items=0.50+N*0.10]
    end

    subgraph Scoring["Confidence Check"]
        ESC{overall < 0.7<br/>or ocr < 0.6<br/>or unverified merchant<br/>or reconciliation?}
    end

    subgraph Vision["Stage 2: Bedrock Vision LLM"]
        VLLM[Converse API<br/>Amazon Nova Lite]
        VPARSE[JSON Extraction]
    end

    subgraph Text["Stage 3: Text LLM Fallback"]
        TLLM[Text-only LLM<br/>Raw OCR text → JSON]
    end

    subgraph Degraded["Stage 4: Degraded"]
        DEG[Partial fields<br/>Default values]
    end

    subgraph Merge["Merge & Output"]
        DETECT[Discrepancy Detection<br/>float tolerance + string norm]
        FM[rapidfuzz ≥80%<br/>→ merchant confidence 0.95]
        MERGE[_merge_results<br/>Highest confidence wins]
        FINAL[StructuredReceipt<br/>+ per-field confidence]
    end

    IMG --> TESS
    TESS --> RE --> SCORE
    SCORE --> ESC

    ESC -->|Keep| MERGE
    ESC -->|Escalate| VLLM
    VLLM --> VPARSE --> DETECT
    VLLM -->|LLM fails| TLLM
    TLLM -->|LLM fails| DEG
    DEG --> MERGE

    DETECT --> FM --> MERGE
    MERGE --> FINAL

    style TESS fill:#1a3a5c,color:#fff
    style SCORE fill:#2d5a1a,color:#fff
    style VLLM fill:#5a1a3a,color:#fff
    style DEG fill:#5a2d1a,color:#fff
```

**Cascade configuration (from `config.py`):**

| Parameter                      | Value | Description                                     |
| ------------------------------ | ----- | ----------------------------------------------- |
| `CASCADE_CONFIDENCE_THRESHOLD` | 0.7   | Overall confidence floor before escalation      |
| `CASCADE_OCR_CONFIDENCE_FLOOR` | 0.6   | OCR field confidence floor                      |
| `MERCHANT_RAPIDFUZZ_THRESHOLD` | ≥80   | Match confidence for known merchants            |
| `MERCHANT_FUZZY_CONFIDENCE`    | 0.95  | Boosted confidence on fuzzy match               |
| `REDIS_CACHE_TTL`              | 24h   | Avoids re-calling Bedrock for same receipt hash |

**Confidence scoring breakdown:**

| Field    | Base Score    | Boost    | Condition                |
| -------- | ------------- | -------- | ------------------------ |
| Total    | 0.88          | —        | Regex match              |
| Merchant | 0.90          | **0.95** | rapidfuzz match ≥80      |
| Date     | 0.85          | —        | Regex match              |
| Items    | 0.50 + N×0.10 | —        | Per line item recognized |

**Escalation triggers** are logged as structured comma-joined reasons for observability — enabling debugging and threshold tuning without reproducing user receipts.

---

### ⚡ Rust Features Engine

Native Rust extension via **PyO3/Maturin** replacing Python's pandas-based indicator computation with zero-cost abstractions. Called directly from Python as a `pip install`-ed wheel, built in CI with `maturin build --release` for ARM64.

**Exported functions:**

| Function                     | Parameters                | Returns                                   | Complexity |
| ---------------------------- | ------------------------- | ----------------------------------------- | ---------- |
| `compute_log_returns`        | close, periods            | `dict` of series                          | O(n)       |
| `compute_moving_averages`    | close, windows            | `dict` of SMA series                      | O(n×k)     |
| `compute_rsi`                | close, period             | RSI series                                | O(n)       |
| `compute_macd`               | close, fast, slow, signal | `dict`: macd_line, signal_line, histogram | O(n)       |
| `compute_rolling_volatility` | close, period             | Volatility series                         | O(n)       |
| `compute_volatility_rank`    | close, period             | Percentile rank series                    | O(n log n) |
| `compute_bollinger`          | close, period, num_std    | `dict`: upper, middle, lower              | O(n)       |
| `compute_atr`                | high, low, close, period  | ATR series (Wilder's)                     | O(n)       |
| `compute_obv`                | close, volume             | OBV series                                | O(n)       |
| `compute_williams_r`         | high, low, close, period  | Williams %R series                        | O(n)       |
| `compute_roc`                | close, period             | Rate of Change series                     | O(n)       |
| `compute_all_features`       | close, high, low, volume  | All 17 features in one call               | Batched    |

**Source modules:**

```
backend/ml/features-engine/src/
├── lib.rs                 # PyO3 module registration + Python wrappers
├── log_returns.rs         # Multi-period log returns
├── moving_averages.rs     # Simple moving averages (multi-window)
├── rsi.rs                 # Relative Strength Index (Wilder's)
├── macd.rs                # MACD + signal + histogram
├── rolling_volatility.rs  # Rolling standard deviation
├── volatility_rank.rs     # Rolling percentile rank
├── bollinger.rs           # Bollinger Bands %B
├── atr.rs                 # Average True Range (Wilder's)
├── obv.rs                 # On-Balance Volume
├── williams_r.rs          # Williams %R oscillator
├── roc.rs                 # Rate of Change
└── compute_all.rs         # Batched feature computation
```

> **Ponytail note:** EMA uses a simple leading-NaN skip rather than a streaming incremental approach — the O(span) seed scan adds negligible overhead at batch sizes of 30–500 rows per ticker and avoids maintaining state across calls.

---

### Portfolio Analytics

**Time-weighted return (TWR)** calculation that correctly handles cash flows — no approximations, no simple-Dietz shortcuts. Benchmark comparison with **Tracking Error** and **Information Ratio**.

**Architecture:**

```mermaid
flowchart LR
    subgraph Input["Data Sources"]
        YH[yfinance<br/>ThreadPoolExecutor 8 workers]
        PG[(PostgreSQL<br/>Transactions + Cash Flows)]
    end

    subgraph Cache["Hybrid Cache Strategy"]
        PG_CACHE[PostgreSQL OHLCV<br/>ticker + date range<br/>indexed for bulk reads]
        REDIS[Redis Quote Cache<br/>TTL: 5 min quotes<br/>60 min historical]
    end

    subgraph Compute["Portfolio Engine"]
        TWR[Time-Weighted Return<br/>Cash-flow aware]
        MKT[Market Data<br/>Latest quotes + history]
        BENCH[Benchmark<br/>SPY comparison]
    end

    subgraph Metrics["Performance Metrics"]
        TE[Tracking Error]
        IR[Information Ratio]
        VOL[Volatility<br/>(annualized)]
    end

    YH --> PG_CACHE
    YH --> REDIS
    PG --> TWR
    PG_CACHE --> MKT
    REDIS --> MKT
    MKT --> BENCH
    TWR --> BENCH
    BENCH --> TE
    BENCH --> IR
    BENCH --> VOL

    style PG_CACHE fill:#2d3a6c,color:#fff
    style REDIS fill:#6c2d2d,color:#fff
```

**Design rationale** (documented in ADR-003, ADR-004):

| Decision                                          | Why                                                                                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Hybrid cache** — PG for OHLCV, Redis for quotes | OHLCV data is large and immutable → indexed PG table with efficient range queries; quotes are small and volatile → Redis with field-specific TTL |
| **Separate market + performance modules**         | Clean isolation: yfinance wrapping (rate-limited thread pool) doesn't leak into the pure TWR/benchmark logic                                     |
| **Synchronous yfinance**                          | yfinance's async client is incomplete; wrapped with `run_in_executor` (8 workers) and `tenacity` retries (ADR-001)                               |
| **Explicit cash_flows table**                     | Each cash flow is a dated, typed row — eliminates the ambiguity of a generic ledger and makes TWR provably correct (ADR-002)                     |

---

### MLOps & Retraining Pipeline

Weekly retraining orchestrated by **Apache Airflow 2.11**, with automated **champion/challenger evaluation** and **distribution-drift monitoring** via Evidently AI.

```mermaid
flowchart TB
    subgraph Weekly["Weekly Schedule"]
        START((Cron<br/>Monday 06:00 UTC))
    end

    subgraph Training["Training Pipeline"]
        FETCH[Fetch 6yr OHLCV<br/>yfinance thread pool]
        COMP[Compute 17 features<br/>Rust features-engine]
        SPLIT[Chronological 70/15/15]
        MLFLOW[MLflow Run<br/>Optuna params logged]
        TRAINPT[PyTorch Training<br/>100 epochs]
    end

    subgraph Eval["Champion / Challenger"]
        CHAL[Challenger<br/>New weekly candidate]
        CHAMP[Champion<br/>Current production model]
        COMPARE{da_improvement<br/>> 0.02?}
        PROMOTE[Promote to champion<br/>disk + S3 + model_registry DB]
        SKIP[Keep existing champion]
    end

    subgraph Drift["Evidently AI Drift Detection"]
        REF[Reference Distributions<br/>Captured at champion time]
        CURRENT[Current production data<br/>Features + predictions]
        PSI[PSI > 0.25?]
        KS[KS > 0.3?]
        JS[JSD > 0.3?]
        ALERT[Drift Alert<br/>→ S3 drift report]
    end

    subgraph Storage["Artifact Storage"]
        S3[(S3 — model.pt<br/>drift reports)]
        DB[(PG model_registry<br/>champion metadata)]
        DISK[(EFS — champion<br/>zero-copy inference)]
    end

    START --> FETCH
    FETCH --> COMP
    COMP --> SPLIT
    SPLIT --> MLFLOW
    MLFLOW --> TRAINPT

    TRAINPT --> CHAL
    COMPARE -->|Yes| PROMOTE
    COMPARE -->|No| SKIP

    CHAL --> COMPARE
    CHAMP --> COMPARE

    PROMOTE --> REF
    CHAMP --> CURRENT

    CURRENT --> PSI
    CURRENT --> KS
    CURRENT --> JS
    PSI -->|Drifted| ALERT
    KS -->|Drifted| ALERT
    JS -->|Drifted| ALERT

    PROMOTE --> S3
    PROMOTE --> DB
    PROMOTE --> DISK

    style Eval fill:#2d1a3a,color:#fff
    style Drift fill:#3a1a1a,color:#fff
```

**MLOps configuration:**

| Component               | Detail                                                                                        |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| **Orchestrator**        | Apache Airflow 2.11 on ECS Fargate ARM64                                                      |
| **Schedule**            | Weekly, Monday 06:00 UTC (cron)                                                               |
| **Experiment tracking** | MLflow 3.14 — every training run logged with hyperparameters, loss curves, evaluation metrics |
| **Model registry**      | PostgreSQL `model_registry` table — tracks champion model ID, S3 URI, performance metrics     |
| **Champion promotion**  | `da_improvement > 0.02` (2 percentage points improvement)                                     |
| **Champion delivery**   | EFS mount (zero-copy) + S3 (durable/CloudFront) + model_registry DB                           |
| **Drift detection**     | Evidently AI — PSI threshold=0.25, KS threshold=0.3, JSD threshold=0.3                        |
| **Drift reporting**     | Reports stored at `s3://stocklens-drift-reports-dev/drift_reports/`                           |
| **Serving backends**    | Fargate (EFS mount) or optional SageMaker endpoint (`ml.m5.xlarge`)                           |
| **Prediction logging**  | 90-day retention in PostgreSQL for offline analysis                                           |

---

## Design Decisions

Every non-trivial design choice is documented in an Architecture Decision Record (ADR). Here are the trade-offs that shaped StockLens:

| Decision                                    | Alternatives Considered                    | Why We Chose This                                                                                                                    |
| ------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Synchronous yfinance** (ADR-001)          | Async yfinance SDK, direct API calls       | yfinance async client is incomplete; `run_in_executor` thread pool + `tenacity` retries gives async benefits without SDK limitations |
| **Explicit cash_flows table** (ADR-002)     | Generic ledger, simple-Dietz approximation | Unambiguous TWR computation; dated+typed rows make cash-flow handling provably correct vs. ledger ambiguity                          |
| **Hybrid cache** (ADR-003)                  | All-Redis, all-PostgreSQL, no cache        | OHLCV is large/immutable → indexed PG table; quotes are small/volatile → Redis with short TTL; avoids memory pressure on Redis       |
| **Separate market + performance** (ADR-004) | Monolithic combined module                 | Clean isolation: yfinance wrapping (thread-pool, rate-limited) doesn't taint the pure TWR/benchmark logic                            |
| **Champion model via EFS** (ADR-006)        | Only S3, only SageMaker                    | EFS mount = zero-copy inference on Fargate; S3 for durable storage + CloudFront delivery; SageMaker as optional serving backend      |
| **Bedrock SigV4 only** (ADR-007)            | Separate API key auth                      | Bedrock uses AWS SigV4 natively; phantom `BEDROCK_API_KEY` would be unused and a security concern                                    |
| **Terraform remote state S3+DDB** (ADR-008) | Local state, Terraform Cloud, Consul       | S3 + DynamoDB = free, auditable, no vendor lock; `use_lockfile` enables collaborative apply safety                                   |
| **ARM64/Graviton** (ADR-009)                | x86_64 Fargate, EC2, Lambda                | ARM64 = 20-30% cost savings at same perf; Fargate removes EC2 management; QEMU cross-build in CI for Rust wheel                      |
| **LangGraph manual StateGraph**             | `create_react_agent` convenience wrapper   | Explicit control over agentic loop; manual history management enables two-tier Redis+RDS persistence                                 |
| **Focal loss for classification**           | Cross-entropy, weighted CE                 | Focal loss (γ=1.49) emphasizes hard misclassifications in imbalanced market regimes; tuned via Optuna                                |
| **Evidently for drift**                     | whylogs, Alibi Detect, custom              | Evidently's PSI/KS/JSD suite covers distribution, feature, and model drift in one library; lightweight, Airflow-native               |

---

## Testing Philosophy

The codebase enforces a **three-tier testing strategy** with explicit coverage gates in CI:

| Tier         | Framework                                           | Scale                                                                        | Coverage Gate                                              |
| ------------ | --------------------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **Backend**  | pytest + pytest-asyncio + pytest-cov + pytest-xdist | 77 test files, 1,415 test functions, parallel with `-n auto --dist loadfile` | `--cov-fail-under=90` (line coverage)                      |
| **Frontend** | Jest + React Native Testing Library + jest-expo     | 85 test files, 822 test assertions                                           | Branches: 75%, Functions: 80%, Lines: 90%, Statements: 80% |
| **Rust**     | cargo test + clippy                                 | 13 source modules                                                            | `cargo clippy -- -D warnings` + `cargo test`               |

**Test suite breakdown (backend — 76 files, 1,415 functions):**

| Category          | Files | Focus                                                     |
| ----------------- | ----- | --------------------------------------------------------- |
| **Agent**         | 6     | LangGraph ReAct agent, tool registry, routing, eval       |
| **Auth**          | 5     | JWT login/register/refresh/logout, bcrypt, rate limiting  |
| **Cache**         | 4     | Redis OHLCV cache, quote cache, TTL behaviour             |
| **Cash flows**    | 4     | TWR computation, explicit cash_flows table                |
| **Market**        | 7     | yfinance wrapper, OHLCV fetch, quote cache, rate limiting |
| **Portfolios**    | 8     | CRUD, analytics, holdings, sector exposure                |
| **Prediction**    | 5     | LSTM inference, champion loading, EFS mount               |
| **Receipts**      | 6     | OCR cascade (Tesseract → LLM), rapidfuzz matching         |
| **Transactions**  | 7     | CRUD, holdings recalculation, cash flow linking           |
| **Core / Config** | 13    | Pydantic settings, DB session, middleware, health         |

**Key testing patterns:**

- **Database-backed tests:** Integration tests spin up real PostgreSQL (`postgres:18-alpine`) and Redis (`redis:8.8-alpine`) via `docker compose --profile test`; the `_migrate_db` fixture handles Alembic migrations once per session
- **Parallel execution:** `pytest -n auto --dist loadfile` distributes tests across CPU cores for fast CI feedback
- **Rate limiter bypass:** Test environment sets `RATE_LIMIT_LOGIN=1000/second` to avoid false throttling
- **Mock-free agent tests:** `test_registry_has_expected_names` confirms exactly 16 tools registered in the LangGraph agent
- **CI-enforced gates:** Merges are blocked below 90% backend line coverage; frontend has per-category coverage floors
- **CI services:** PostgreSQL 18 + Redis 7 spun up as GitHub Actions service containers
- **Property-based:** Hypothesis-driven tests for TWR calculation and cash-flow invariants
- **Mutation testing:** `mutmut` runs nightly on critical paths (TWR, LSTM inference, OCR parsing)

---

## Infrastructure (Terraform)

All AWS infrastructure is defined as Terraform ≥1.9 modules with **S3 remote state** and **DynamoDB `use_lockfile` locking** (ADR-008).

**VPC topology:**

```mermaid
flowchart TB
    subgraph VPC["VPC — eu-west-2"]
        direction TB

        subgraph AZ1["Availability Zone A"]
            PUB1[Public Subnet<br/>10.0.1.0/24]
            PRIV1[Private Subnet<br/>10.0.10.0/24]
        end

        subgraph AZ2["Availability Zone B"]
            PUB2[Public Subnet<br/>10.0.2.0/24]
            PRIV2[Private Subnet<br/>10.0.11.0/24]
        end
    end

    IGW[Internet Gateway]
    NAT[NAT Gateway]

    WAF[AWS WAF<br/>Rate-based + OWASP rules]
    ALB[Application<br/>Load Balancer]

    subgraph Compute["ECS Fargate ARM64"]
        ECS_API[FastAPI Backend<br/>256 CPU / 512 MB<br/>min=2, max=6]
        ECS_AGENT[LangGraph Agent<br/>Same cluster]
        ECS_AIRFLOW[Airflow<br/>2.11.0]
        ECS_MLFLOW[MLflow<br/>3.14.0 server]
    end

    RDS[(RDS PostgreSQL<br/>Multi-AZ<br/>db.t4g.micro<br/>20GB → 100GB)]
    RC[(ElastiCache Redis<br/>cache.r6g.micro<br/>TLS + AUTH)]

    EFS[(EFS<br/>Champion model.pt)]

    S3_BUCKETS[<table border="0"><tr><td>📦 MLflow Artifacts</td></tr><tr><td>📊 Drift Reports</td></tr><tr><td>🏆 Champion Model</td></tr><tr><td>☁️ CloudFront CDN</td></tr></table>]

    CW[CloudWatch<br/>Logs + Metrics + Alarms<br/>Budget: $100/month]

    IGW --> WAF --> ALB
    ALB --> PUB1
    ALB --> PUB2

    PUB1 --> NAT
    PUB2 --> NAT

    NAT --> PRIV1
    NAT --> PRIV2

    PRIV1 --> ECS_API
    PRIV2 --> ECS_API
    PRIV1 --> ECS_AGENT
    PRIV2 --> ECS_AGENT

    ECS_API --> RDS
    ECS_API --> RC
    ECS_API --> S3_BUCKETS
    ECS_API --> EFS

    ECS_AGENT --> RDS
    ECS_AGENT --> RC

    PRIV1 --> ECS_AIRFLOW
    PRIV2 --> ECS_MLFLOW

    ECS_AIRFLOW --> RDS
    ECS_AIRFLOW --> S3_BUCKETS

    style VPC fill:#1a1a2e,color:#fff
    style AZ1 fill:#1a2a1a,color:#fff
    style AZ2 fill:#1a2a1a,color:#fff
    style Compute fill:#2d2d4a,color:#fff
```

**Terraform modules:**

| Module         | Resources                                                                       | Configuration                                |
| -------------- | ------------------------------------------------------------------------------- | -------------------------------------------- |
| **vpc**        | VPC, public/private subnets (2 AZs), IGW, NAT Gateway                           | 10.0.0.0/16, 2 AZs (eu-west-2a/b)            |
| **network**    | Security groups — ALB, ECS tasks, RDS, Redis, MLflow, Airflow                   | Least-privilege ingress/egress rules         |
| **secrets**    | AWS Secrets Manager — DB password, JWT secret, Redis auth, LangSmith key        | Auto-generated if empty                      |
| **s3**         | S3 buckets — MLflow artifacts, drift reports, champion model                    | KMS encryption, CloudFront origin            |
| **database**   | RDS PostgreSQL — Multi-AZ, automated backups, Performance Insights              | `db.t4g.micro`, 20 GB → 100 GB autoscaling   |
| **cache**      | ElastiCache Redis — TLS, AUTH token, encryption at rest                         | `cache.r6g.micro`, single node               |
| **iam**        | IAM roles — ECS execution, task, SageMaker, EventBridge, OIDC deploy            | Least-privilege, per-resource scope          |
| **compute**    | ECS Fargate cluster, service, task definition, ALB, target groups, Auto Scaling | ARM64, min=2, max=6, CPU 70%/RPS 100 targets |
| **mlflow**     | MLflow Fargate service, SQLite backend, shared EFS                              | Sidecar to Airflow                           |
| **airflow**    | Airflow Fargate service, DB connection, MLflow integration                      | Weekly schedule via EventBridge              |
| **waf**        | AWS WAF — rate-based rules, SQL injection, XSS blocks                           | 2000 req/s (prod) / 5000 (dev)               |
| **monitoring** | CloudWatch dashboards, alarms, SNS notifications                                | CPU, memory, RDS connections, Redis          |
| **sagemaker**  | SageMaker model, endpoint config, endpoint (optional)                           | `ml.m5.xlarge`, 600s timeout                 |
| **budgets**    | AWS Budgets — monthly limit, SNS alerts                                         | $100/month default                           |

---

## CI/CD Pipeline

Two pipelines run on every push to `main`:

**CI pipeline** — 9 parallel jobs, each blocking if it fails:

```mermaid
flowchart LR
    PUSH[git push] --> CI

    subgraph CI["CI — 9 Parallel Jobs"]
        LINT[Lint & Format<br/>Prettier + ESLint]
        TS[TypeScript<br/>tsc --noEmit]
        FE_TEST[Frontend Tests<br/>Jest + coverage]
        SEC[Security Audit<br/>npm audit]
        RUST[Rust<br/>clippy + cargo test]
        PY_TEST[Backend Tests<br/>pytest + 90% cov]
        DOCKER[Docker Validation<br/>hadolint + compose]
        IAC[IaC Security<br/>Checkov + tfsec]
        SECRET[Secret Scan<br/>Gitleaks]
    end

    CI -->|All pass| CD_TRIGGER

    LINT --> PASS
    TS --> PASS
    FE_TEST --> PASS
    SEC --> PASS
    RUST --> PASS
    PY_TEST --> PASS
    DOCKER --> PASS
    IAC --> PASS
    SECRET --> PASS
```

**CD pipeline** — 7 stages (manual approval before apply):

```mermaid
flowchart LR
    subgraph BUILD["Build"]
        FE_WHEEL[Build Rust<br/>features-engine<br/>ARM64 wheel]
        BE_IMG[Build Backend<br/>ARM64 Docker<br/>ECR push]
        AF_IMG[Build Airflow<br/>ARM64 Docker<br/>ECR push]
        ML_IMG[Build ML Training<br/>x86_64 Docker<br/>ECR push]
        SM_IMG[Build SageMaker<br/>ARM64 Docker<br/>ECR push]
    end

    subgraph SCAN["Security Scan"]
        TRIVY[Trivy<br/>Critical vulns<br/>→ fail]
    end

    subgraph PLAN["Plan"]
        TF_INIT[terraform init]
        TF_PLAN[terraform plan<br/>-var=image tags]
        PLAN_OUT[Plan artifact<br/>+ GH summary]
    end

    subgraph APPROVE["Manual Approval"]
        GATE[Production<br/>environment gate]
    end

    subgraph APPLY["Apply"]
        TF_APPLY[terraform apply<br/>tfplan]
        ECS_UPDATE[ECS service<br/>rolled update]
    end

    FE_WHEEL --> BE_IMG
    FE_WHEEL --> AF_IMG
    BE_IMG --> SM_IMG

    BE_IMG --> TRIVY
    AF_IMG --> TRIVY
    ML_IMG --> TRIVY
    SM_IMG --> TRIVY

    TRIVY --> TF_INIT
    TF_INIT --> TF_PLAN
    TF_PLAN --> PLAN_OUT

    PLAN_OUT --> GATE
    GATE -->|Approved| TF_APPLY
    TF_APPLY --> ECS_UPDATE

    style BUILD fill:#1a2a3a,color:#fff
    style SCAN fill:#3a1a1a,color:#fff
    style PLAN fill:#2d3a1a,color:#fff
    style APPROVE fill:#3a2d1a,color:#fff
    style APPLY fill:#1a3a2a,color:#fff
```

**CI configuration summary:**

| Job            | Tool                            | Key Config                                                   |
| -------------- | ------------------------------- | ------------------------------------------------------------ |
| Lint & Format  | Prettier 3.9 + ESLint 9         | `prettier --check .`, `eslint frontend/src/`                 |
| TypeScript     | tsc                             | `tsc --noEmit`                                               |
| Frontend Tests | Jest 29 + jest-expo 54          | Coverage: branches≥75, functions≥80, lines≥90, statements≥80 |
| Security Audit | npm audit                       | `--omit=dev`                                                 |
| Rust           | cargo + clippy                  | `cargo clippy -- -D warnings`, `cargo test`                  |
| Backend Tests  | pytest 8+ (xdist, cov, asyncio) | PG 18 + Redis 7 services, `--cov-fail-under=90`              |
| Docker         | hadolint + compose              | `docker compose config --quiet`, `hadolint Dockerfile*`      |
| IaC            | Checkov + tfsec                 | `checkov --directory terraform/`, `tfsec terraform/`         |
| Secrets        | Gitleaks                        | Full git history scan                                        |

**CD pipeline stages:**

| Stage                | What It Does                                             |
| -------------------- | -------------------------------------------------------- |
| ⚙️ Build Rust wheel  | Docker Buildx ARM64 → `maturin build --release`          |
| 🐳 Build+Push images | Backend, Airflow, ML Training (`amd64`), SageMaker → ECR |
| 🔬 Container scan    | Trivy — critical severity only, blocks on findings       |
| 📋 Terraform plan    | Plan with `-lock=false`, outputs to GH job summary       |
| ✅ Manual approval   | Production environment gate in GitHub                    |
| 🚀 Terraform apply   | Applies reviewed plan, ECS service updated               |
| 📦 ECS update        | Rolling update with zero-downtime via Fargate            |

---

## Security Model

| Layer              | Mechanism                                                                                        | Details                                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Authentication** | JWT access + refresh tokens, bcrypt (12 rounds)                                                  | Access TTL: 15 min; Refresh TTL: 7 days; rotation on refresh; `slowapi` rate limiting (login: 5/min)                                 |
| **Authorization**  | Role-based (user/admin via JWT `role` claim)                                                     | Admin-only endpoints guarded by `require_admin` dependency; ownership checks on portfolio/transaction resources                      |
| **Secrets**        | AWS Secrets Manager + GitHub Actions OIDC                                                        | DB password, JWT secret, Redis auth, LangSmith key — injected at container start; zero static secrets in repo                        |
| **Network**        | Three-tier VPC: Public (ALB/WAF) → Private (ECS Fargate) → Data (RDS/ElastiCache)                | Security groups: ALB→ECS (8000), ECS→RDS (5432), ECS→Redis (6379), ECS→Bedrock (443 egress); no direct internet from private subnets |
| **Transport**      | TLS 1.2+ everywhere                                                                              | ALB terminates HTTPS (ACM cert); RDS/ElastiCache enforce TLS; internal ECS-to-ECS via service discovery (no mTLS yet)                |
| **WAF**            | AWS WAF on ALB                                                                                   | Rate-based rules (2000 req/5min), OWASP Core Rule Set (SQLi, XSS), IP blocklist                                                      |
| **Container**      | Non-root user, read-only rootfs, distroless-like base                                            | Backend: `python:3.13-slim` → non-root `appuser`; Frontend: nginx alpine; ARM64 Graviton                                             |
| **Supply Chain**   | `pip-audit` + `npm audit` + `cargo audit` in CI; Trivy critical-only scan; Gitleaks full-history | SBOM via `syft` on release; `pip-tools` lockfile; `uv` for reproducible Python deps                                                  |
| **Data**           | Encryption at rest + in transit                                                                  | RDS: AES-256; ElastiCache: AES-256 + TLS; S3: SSE-S3; EFS: AES-256; EBS: AES-256                                                     |
| **Audit**          | CloudTrail data events + application structured logging (structlog)                              | All admin actions, auth events, and agent tool calls logged with request ID; CloudWatch log groups per service                       |
| **CI/CD**          | OIDC federation (no static AWS keys); Checkov + tfsec IaC scan; CodeQL weekly                    | PRs blocked on any high/critical finding; terraform plan posted as PR comment                                                        |

---

## Getting Started

### Prerequisites

- **Docker** + Docker Compose (for local dev stack)
- **Python 3.13** (runtime only — all services run in containers)
- **Node.js 20+** and **npm** (for frontend development)
- **AWS CLI** + **Terraform ≥1.9** (for production deployment)

### Quick Start (Local Development)

```bash
git clone https://github.com/AhmedIkram05/StockLens.git
cd StockLens
cp .env.example .env                          # or create .env with required keys

# Start local dev stack (PostgreSQL, Redis, MLflow, Backend)
docker compose up -d

# Frontend (separate terminal)
cd frontend
npm install
npx expo start                                # or: npx expo start --ios / --android
```

Backend API: `http://localhost:8000` (docs at `/docs`)
MLflow UI: `http://localhost:5001`
PostgreSQL: `localhost:5434` (user/pass: `stocklens`/`stocklens`)
Redis: `localhost:6379`

### Configuration

All configuration is via environment variables (Pydantic Settings). Key variables:

| Variable                | Description                                 | Default                                                             |
| ----------------------- | ------------------------------------------- | ------------------------------------------------------------------- |
| `DATABASE_URL`          | PostgreSQL connection string                | `postgresql+asyncpg://stocklens:stocklens@localhost:5434/stocklens` |
| `REDIS_URL`             | Redis connection string                     | `redis://localhost:6379/0`                                          |
| `JWT_SECRET_KEY`        | JWT signing key (generate: 2 signing secret | **required** — generate via `openssl rand -hex 32`                  |
| `ALPHA_VANTAGE_API_KEY` | Market data provider                        | **required** for quotes/OHLCV                                       |
| `AWS_REGION`            | AWS region for Bedrock/Secrets Manager      | `eu-west-2`                                                         |
| `BEDROCK_MODEL_ID`      | LLM model for agent                         | `amazon.nova-lite-v1:0`                                             |
| `MLFLOW_TRACKING_URI`   | MLflow tracking server                      | `http://localhost:5001`                                             |

See `.env.example` for the full list.

### Running Tests

```bash
# Backend (pytest)
cd backend
uv run pytest -n auto --cov=src

# Frontend (Jest - per-category gates)
cd frontend
npm test -- --watchAll=false --coverage

# Rust features engine
cd backend/ml/features-engine
cargo test && cargo clippy -- -D warnings
```

### Production Deployment

```bash
cd terraform
terraform init
terraform plan -var="image_tag=sha-<GIT_SHA>"
terraform apply

# Or use the CD pipeline: push to main → GitHub Actions OIDC → 7-stage deploy
```

For full production deployment guide including secrets bootstrap, domain setup, and monitoring, see [docs/deployment.md](docs/deployment.md) (if available).

---

## Project Structure

```
StockLens/
├── backend/
│   ├── Dockerfile                    # Multi-stage: python:3.13-slim build → runtime
│   ├── Dockerfile.agent              # Agent service (LangGraph + Bedrock)
│   ├── Dockerfile.airflow            # Airflow scheduler + webserver
│   ├── Dockerfile.ml-training        # ML training (x86_64 for SageMaker compat)
│   ├── Dockerfile.sagemaker          # SageMaker inference container
│   ├── pyproject.toml                # uv/pip-tools dependencies, pytest config
│   ├── src/
│   │   ├── api/                      # FastAPI app: routers, middleware, deps
│   │   ├── auth/                     # JWT, bcrypt, rate limiting
│   │   ├── cache/                    # Redis OHLCV + quote cache
│   │   ├── market/                   # yfinance wrapper + market data
│   │   ├── ml/                       # LSTM model, inference, features
│   │   │   ├── features-engine/      # Rust PyO3 extension (13 modules)
│   │   │   ├── lstm/                 # PyTorch Global LSTM
│   │   │   └── training/             # Optuna HPO, training loop
│   │   ├── portfolio/                # TWR, holdings, sector, benchmark
│   │   ├── receipts/                 # OCR cascade (Tesseract → Bedrock)
│   │   ├── agent/                    # LangGraph ReAct agent + 16 tools
│   │   ├── transactions/             # CRUD + holdings recalc + cash flows
│   │   ├── config.py                 # Pydantic Settings (env-driven)
│   │   └── database/                 # SQLAlchemy 2.0 models, Alembic
│   └── tests/                        # 76 files, 1415 functions
├── frontend/
│   ├── Dockerfile                    # Multi-stage: node:20-alpine → nginx alpine
│   ├── package.json                  # Expo 54, React Native 0.81, TypeScript 5.9
│   ├── src/
│   │   ├── app/                      # Expo Router file-based routing
│   │   ├── components/               # Reusable UI components
│   │   ├── hooks/                    # Custom React hooks
│   │   ├── services/                 # API client, auth, storage
│   │   ├── store/                    # Zustand state management
│   │   └── utils/                    # Helpers, formatters
│   └── __tests__/                    # 85 test files, 822 assertions
├── terraform/
│   ├── main.tf                       # Root module, provider, backend
│   ├── variables.tf                  # Input variables
│   ├── outputs.tf                    # Module outputs
│   ├── modules/                      # 14 Terraform modules
│   │   ├── vpc/, network/, secrets/, s3/
│   │   ├── database/, cache/, iam/, compute/
│   │   ├── mlflow/, airflow/, waf/, monitoring/
│   │   ├── sagemaker/, budgets/
│   └── environments/                 # dev/prod variable files
├── docker-compose.yml                # Local dev: backend + agent
├── docker-compose.postgres.yml       # PostgreSQL (standalone)
├── docker-compose.redis.yml          # Redis (standalone)
├── docker-compose.mlflow.yml         # MLflow tracking server
├── docker-compose.airflow.yml        # Airflow (optional)
├── Makefile                          # up/down/logs/rebuild/shell
├── .env.example                      # All required env vars documented
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                    # 9 parallel CI jobs
│   │   ├── cd.yml                    # 7-stage CD pipeline
│   │   ├── codeql.yml                # Weekly CodeQL analysis
│   │   └── dependabot.yml            # Weekly dep updates
│   └── dependabot.yml
└── docs/
    ├── adr/                          # 9 Architecture Decision Records
    ├── deployment.md                 # Production deployment guide
    └── demos/                        # 15 demo assets (6 MOV, 6 MP4, 3 PNG)
```

---

## Documentation

| Doc                                              | What it covers                                                      |
| ------------------------------------------------ | ------------------------------------------------------------------- |
| [ADR Index](docs/adr/README.md)                  | All 9 Architecture Decision Records with trade-offs and rationale   |
| [Deployment Guide](docs/deployment.md)           | Production deployment: secrets bootstrap, domain setup, monitoring  |
| [API Reference](docs/api-reference.md)           | Complete `/api/v1/*` routes, request/response schemas, auth methods |
| [Configuration Reference](docs/configuration.md) | All environment variables with descriptions and defaults            |
| [ML Model Card](docs/model-card.md)              | LSTM model details, training data, performance, limitations         |

---

## Related Projects

- [**LAAD**](https://github.com/AhmedIkram05/laad) — ATM Log Aggregation & Diagnostics Platform: production data engineering pipeline with RAG diagnostic assistant, parallel Airflow ETL, and Power BI analytics
- [**DevSync**](https://github.com/AhmedIkram05/DevSync) — Full-stack project management platform with real-time collaboration, GitHub OAuth 2.0 integration, and bidirectional Issue/PR sync (React + Flask + PostgreSQL)
- [**W3C ETL Pipeline**](https://github.com/AhmedIkram05/W3C-ETL-Pipeline) — Massively parallel Airflow ETL processing 100M+ web log entries with Power BI dashboards
