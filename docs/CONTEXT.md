# StockLens — Domain Glossary

> **Purpose:** Shared vocabulary across all phases. Updated per-phase.
> **Audience:** AI coding agents implementing any phase.
> **All terms defined here are normative** — if implementation docs use different language, this glossary wins.
>
> **Phase 6 terms added:** 2026-07-13 (Conversational Finance Agent — LangGraph)

---

## Market Data

| Term               | Definition                                                                                                        | Attributes / Constraints                                                                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ticker**         | Exchange-traded symbol (e.g. `AAPL`, `SPY`, `QQQ`).                                                               | Upper case, 1–10 chars. Identical to the `ticker` column in `holdings`, `transactions`, `ohlcv_prices`.                                                    |
| **OHLCV**          | Open / High / Low / Close / Volume — the standard daily price record.                                             | `open, high, low, close, adjusted_close`: DECIMAL(12,4). `volume`: BIGINT.                                                                                 |
| **Adjusted Close** | Closing price adjusted for splits and dividends. Used for return calculations so historical returns are accurate. | Stored in `ohlcv_prices.adjusted_close`. Used by all return computations.                                                                                  |
| **Quote**          | A real-time (or near-real-time) price snapshot for a ticker.                                                      | Contains: `ticker`, `price`, `change`, `change_pct`, `previous_close`, `volume`, `timestamp`.                                                              |
| **Data Freshness** | Age of cached market data. Determines whether a cache-hit is returned or a fetch from yfinance is triggered.      | **Historical** (≥1 year ago): cache forever. **Recent** (<1 year): refresh daily after market close. **Quote**: refresh every request (1-min Redis cache). |
| **yfinance**       | The Python library (`yfinance`, unoffical) used to fetch Yahoo Finance data.                                      | Synchronous library wrapped with `asyncio.to_thread()` for non-blocking usage.                                                                             |

### Data Flow

```
Client → FastAPI → market router → yfinance provider → ohlcv_prices (DB cache) → response
                                      │
                                      └──→ If cache is fresh, skip yfinance
```

---

## Portfolio Performance

| Term                      | Definition                                                                                                                                                                              | Formula                                                                                      |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Market Value**          | Current worth of a holding.                                                                                                                                                             | `shares × current_price`                                                                     |
| **Total Portfolio Value** | Sum of market values across all holdings.                                                                                                                                               | `Σ(shares_i × current_price_i)`                                                              |
| **Cost Basis**            | Total amount invested in a holding.                                                                                                                                                     | `shares × average_cost_basis`                                                                |
| **Total Cost Basis**      | Sum of cost bases across all holdings.                                                                                                                                                  | `Σ(shares_i × avg_cost_basis_i)`                                                             |
| **Unrealised P&L**        | Profit/loss on paper (unrealised).                                                                                                                                                      | `market_value − cost_basis`                                                                  |
| **Unrealised P&L %**      | Percentage return on paper.                                                                                                                                                             | `(current_price − avg_cost_basis) / avg_cost_basis × 100`                                    |
| **Day Change**            | Dollar change from previous close.                                                                                                                                                      | `shares × (current_price − previous_close)`                                                  |
| **Day Change %**          | Percentage change from previous close.                                                                                                                                                  | `(current_price − previous_close) / previous_close × 100`                                    |
| **Portfolio Weight**      | Fraction of portfolio in a single holding.                                                                                                                                              | `market_value / total_portfolio_value × 100`                                                 |
| **Net Cash Flow**         | External cash movement for TWR calculation.                                                                                                                                             | Positive = deposit (from cash_flows table). Negative = not supported in V1 (no withdrawals). |
| **Sub-Period Return**     | Return over a period between two cash flows.                                                                                                                                            | `(EMV − BMV − CF) / BMV`                                                                     |
| **TWR**                   | Time-Weighted Return — geometric link of sub-period returns. Industry standard, neutralises cash flow timing. Uses explicit cash_flows records (not inferred from transaction amounts). | `Π(1 + r_i) − 1`                                                                             |
| **Annualised TWR**        | TWR scaled to a 1-year equivalent.                                                                                                                                                      | `(1 + TWR)^(365/days) − 1`                                                                   |
| **Cash Flow (Record)**    | An explicit deposit into a portfolio. Source can be 'receipt' (scan receipt → deposit amount) or 'manual'.                                                                              | Stored in `cash_flows` table. Amount > 0 always (deposits only).                             |
| **Free Cash Balance**     | Uninvested cash in a portfolio.                                                                                                                                                         | `SUM(cash_flows.amount) − SUM(BUY total_amount) + SUM(SELL total_amount)`                    |
| **Receipt Deposit**       | Scanning a physical receipt deposits its `total_amount` as play money. This creates a cash_flow record with source='receipt'. Paper trading: real prices, fake money.                   | Receipt → cash_flow via `source_id` (no FK constraint).                                      |

---

## Benchmark Comparison

| Term                      | Definition                                                                                                                                     | Formula                                                |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| **Benchmark**             | A market index tracked for comparison (SPY, QQQ). Benchmarks have ticker symbols and trade as ETFs, so they have price data in `ohlcv_prices`. | —                                                      |
| **Benchmark Return**      | Total return of a benchmark over the same period.                                                                                              | `(end_price − start_price) / start_price`              |
| **Excess Return (Alpha)** | Portfolio return minus benchmark return.                                                                                                       | `TWR − Benchmark Return`                               |
| **Tracking Error**        | Standard deviation of daily excess returns.                                                                                                    | `σ(portfolio_daily_return − benchmark_daily_return)`   |
| **Information Ratio**     | Risk-adjusted excess return.                                                                                                                   | `Annualised Excess Return / Annualised Tracking Error` |

---

## Caching Strategy

| Cache Layer                     | Scope                       | TTL / Eviction                                                        | Notes                                                              |
| ------------------------------- | --------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **PostgreSQL (`ohlcv_prices`)** | Historical OHLCV per ticker | Cache forever for dates ≥1 year old. Refresh daily for dates <1 year. | Only write, never evict. UNIQUE(ticker, date) prevents duplicates. |
| **Redis**                       | Current quote               | 60 seconds                                                            | Prevents yfinance hammering on refresh-heavy pages.                |
| **In-memory (per request)**     | None                        | N/A                                                                   | Each request fetches fresh, no per-request caching needed.         |

---

## Design Constraints

1. **yfinance is synchronous.** Must be wrapped with `asyncio.to_thread()` or run in a thread pool executor. Cannot use `await yf.download()`.
2. **OHLCV table already exists.** Schema frozen. No migration needed for Phase 2.
3. **No ORM at query time.** All DB access must use asyncpg directly (same pattern as Phase 1).
4. **User-scoped data.** Portfolio performance endpoints must verify ownership (same `user_id` JOIN pattern as Phase 1 holdings).
5. **Decimal precision.** All monetary values use DECIMAL(12,4) in DB, Python `Decimal` in code, serialised as `float` in JSON.
6. **Pydantic for all schemas.** Request/response models use Pydantic v2 with `ConfigDict(json_encoders={Decimal: float})`.

---

## LSTM Model & ML Pipeline (Phase 3)

| Term | Definition | Attributes / Constraints |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Directional Forecast** | The model's prediction: UP (price will rise), FLAT (price will stay within noise band), DOWN (price will fall). | 3-class classification. Confidence ∈ [0, 1] for each class. |
| **Global Model** | A single LSTM trained on 55+ S&P 500 components simultaneously, with ticker entity embeddings to learn ticker-specific patterns. Generalizes to unseen tickers via UNK. | One model with one MLflow run. Not per-ticker models. Train set = 55 tickers (dev), 475 (prod via TRAINING_TICKERS env). |
| **Feature Window** | The 30-trading-day lookback window used to construct each prediction sample. Each sample is 30 rows × N_features. | Fixed at 30 trading days (not calendar days). Defined in both the dataset generator and the model's input layer. |
| **Technical Indicators** | The feature set computed from raw OHLCV for each ticker across 55+ tickers: 17 features — 13 v1 (log returns 1/5/21d, MA 5/10/20/50, RSI(14), MACD line/signal/hist, vol_30d, vol_rank), vol_pct (rolling 30d vol percentile), and 3 cross-sectional excess returns vs SPY (excess_ret_1d/5d/21d). Extra indicators exist in Rust engine (BB, ATR, OBV, Williams %R, ROC) but are dropped in features.py. | All computed from `adjusted_close`. Cross-sectional features require SPY benchmark data in `ohlcv_prices` table. Standardised via **global pooled z-score** (one set of means/stds across all tickers). NaN-padded at sequence boundaries. |
| **Log Returns** | `ln(P_t / P_{t-1})` — the standard transform for financial time series. Used as the primary return metric for labeling and feature engineering. | Daily log returns. Multi-period: 1d, 5d, 21d log returns included as features. |
| **Adaptive Label** | The UP/FLAT/DOWN label computed using a rolling volatility threshold, not a fixed percentage. 5-day forecast horizon (forward return over 5 trading days). | `FLAT` if `                                                                                                                                                                                                                                                   | log_return | < 0.3 × σ_30d × sqrt(horizon)`. `UP`/`DOWN`otherwise.`σ_30d`= rolling 30-day std of daily log returns.`threshold_mult=0.3`(was 0.5 — gave 44% FLAT).`sqrt(horizon)` scaling keeps class balance stable as horizon changes. |
| **Entity Embedding** | A learned vector representation per ticker, used by the Global Model to capture ticker-specific price dynamics while keeping the LSTM weights shared across all tickers. | Vocabulary = all training tickers + UNK token. Embedding dimension = 16 (configurable). UNK embedding is learned for unseen tickers. |
| **Champion Model** | The best-performing registered model in MLflow (by directional accuracy on validation set). Promoted via MLflow Model Registry aliases. | Stored in `model_registry` DB table with alias='champion'. One champion at a time. |
| **MLflow Run** | A single training execution, logged with hyperparameters, loss curves, confusion matrix, evaluation metrics, and the model artifact. | Runs stored in the MLflow tracking server (Docker Compose service) with SQLite backend. |
| **Directional Accuracy** | Percentage of correct direction predictions across all test samples. Not just UP accuracy — all 3 classes. | Computed on the held-out test set (last 15% chronological). |
| **Simulated Sharpe** | Sharpe ratio from a signal-based trading simulation: long the ticker when model predicts UP, flat (cash) when FLAT or DOWN. | Daily returns from the simulated strategy. `Sharpe = mean(daily_return) / std(daily_return) × sqrt(252)`. No transaction costs in V1 (ponytail: add if live trading is implemented). |
| **Long-Short Sharpe** | Sharpe ratio from a symmetric strategy: long UP predictions (+1% when correct), short DOWN predictions (+1% when correct, −1% when wrong), flat on FLAT. | Doubles the signal per prediction for symmetric models. `return = +1%` for correct UP/DOWN, `−1%` for incorrect, 0% for FLAT or incorrect FLAT. Same annualisation as Simulated Sharpe. |
| **Chronological Split** | Train/validation/test split that respects time ordering: earliest 70% of trading days → train, next 15% → validation, last 15% → test. No random shuffle. | Applied globally after merging all tickers' data. Each sample stays in its time bucket based on the last date in its feature window. |
| **Weighted Cross-Entropy** | Cross-entropy loss with class weights inversely proportional to class frequencies. Handles UP/FLAT/DOWN imbalance where FLAT dominates. | `class_weight[c] = total_samples / (n_classes × samples_in_class[c])`. Weights computed per training epoch over the current ticker subset. |
| **Model Quality Limitations** | Directional accuracy ~29% → 53% after R11/R12 improvements (FocalLoss, split-then-normalize, cross-sectional features vs SPY). Test Sharpe 0.97. FLAT class F1 still 0.0 — model rarely predicts FLAT. | Financial time series has inherently low SNR. 17 features (13 V1 + vol_pct + 3 excess returns vs SPY) plus FocalLoss γ=2.0 and vol filtering (bottom 40th pctile removed) gave the largest single improvement (+2.52pp directional acc, +0.26 Sharpe in R12). |

### Data Flow — Prediction

```
Client → GET /predict/{ticker}
  → FastAPI router → prediction_service (lifespan-loaded GlobalLSTM model)
  → Fetch 90+ days of OHLCV from market/repository.py (DB cache)
  → Compute technical indicators (30-day window × N features)
  → Convert to tensor → model forward pass
  → Return { ticker, prediction: "UP"|"FLAT"|"DOWN", confidence, probabilities }
  → Cache result in Redis (6h TTL) for identical ticker queries
```

### Data Flow — Training

```
backend/ml/pipeline.py
   1. Fetch OHLCV for 55+ S&P 500 tickers from ohlcv_prices (6yr lookback)
  2. Compute features + labels per ticker
  3. Build ticker vocabulary → assign embedding indices
  4. Merge all tickers into global dataset with global pooled z-score standardisation
  5. Sort by date globally → chronological split: 70/15/15
  6. Create DataLoaders with SequenceDataset
   7. Initialise GlobalLSTM (vocab_size, embed_dim=16, hidden=64, n_layers=2, dropout=0.5, n_features=17)
   8. Train with AdamW + CosineAnnealingLR + weighted cross-entropy + gradient clipping (max_norm=5.0)
   9. Early stopping (patience 15) on validation loss
  10. Evaluate on test set: directional accuracy, per-class F1, confusion matrix, Simulated Sharpe
  11. Log everything to MLflow (tracking server at http://mlflow:5000)
  12. Register champion model in MLflow Model Registry + persist to model_registry DB
```

### Model Architecture (torch.nn.Module)

```
GlobalLSTM(
  ticker_embedding: Embedding(vocab_size, embed_dim=16, padding_idx=UNK)
  feature_projection: Linear(n_features + embed_dim, hidden_dim=64) → ReLU  // n_features=17 (13 V1 + vol_pct + excess_ret_1d/5d/21d)
  lstm: LSTM(hidden_dim=64, hidden_size=64, num_layers=2, dropout=0.5, batch_first=True, bidirectional=False)
  dropout: Dropout(p=0.5)
  classifier: Linear(64, 3) → logits
)
```

---

## MLOps & Automation (Phase 4)

| Term                       | Definition                                                                                                                                                                                                                                                                                                                       | Attributes / Constraints                                                                                                                                                                                      |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Weekly Retraining DAG**  | An Airflow Directed Acyclic Graph that runs weekly: fetch new OHLCV → retrain GlobalLSTM → evaluate challenger vs champion → promote if >2pp directional accuracy improvement → log results to MLflow.                                                                                                                           | Runs via Airflow LocalExecutor on ECS Fargate (production). Metadata stored in RDS PostgreSQL (no SQLite). EventBridge rule on drift alarm triggers `airflow dags trigger weekly_retraining` via ECS RunTask. |
| **Champion Model**         | The best-performing registered model in MLflow (by directional accuracy on validation set). Promoted via MLflow Model Registry aliases.                                                                                                                                                                                          | Stored in `model_registry` DB table with alias='champion'. One champion at a time.                                                                                                                            |
| **Challenger Model**       | The newly-trained model from the weekly retraining DAG. Evaluated against champion on the held-out test set. Promoted only if directional accuracy > champion + 2pp.                                                                                                                                                             | Not registered in MLflow until promotion. Evaluated within the same DAG run.                                                                                                                                  |
| **Promotion Threshold**    | The minimum directional accuracy improvement required for challenger to replace champion.                                                                                                                                                                                                                                        | Fixed at 2 percentage points (pp) on directional accuracy. Metric computed on the chronological test set (last 15% of data).                                                                                  |
| **Data Drift**             | Distribution shift in input features (log returns, technical indicators) between training-time and inference-time data. Detected via Population Stability Index (PSI) and Kolmogorov-Smirnov (KS) test per feature per ticker.                                                                                                   | Computed for portfolio tickers only + SPY benchmark. Overlapping window: reference distribution from training set, current distribution from production inference data.                                       |
| **Prediction Drift**       | Shift in the model's output distribution over time — the proportion of UP/FLAT/DOWN predictions and the confidence score distribution. Detects silent model degradation when live predictions diverge from training-time distributions.                                                                                          | Tracks class distribution histogram + confidence score histogram. Compared against training-time prediction distribution using JS divergence.                                                                 |
| **JS Divergence**          | Jensen-Shannon divergence — a symmetric, finite measure of difference between two probability distributions. Used to quantify drift magnitude.                                                                                                                                                                                   | Alert threshold: JS divergence > 0.3 on any feature or prediction distribution. 0 = identical distributions, 1 = maximally different.                                                                         |
| **PSI**                    | Population Stability Index — measures how much a feature's distribution has shifted between two time windows. Standard industry metric for monitoring model inputs.                                                                                                                                                              | PSI < 0.1 = no shift, 0.1–0.25 = slight shift (monitor), > 0.25 = significant shift (alert).                                                                                                                  |
| **Drift Report**           | An HTML report generated by Evidently AI containing per-ticker drift analysis: feature-level PSI/KS tests, feature histograms (reference vs current), prediction distribution comparison, and data quality statistics.                                                                                                           | Report scope: portfolio tickers + SPY benchmark. Generated per-drift-run. Stored in S3 with pre-signed URL access. Key metrics also persisted in `drift_metrics` PostgreSQL table.                            |
| **Drift Run**              | An on-demand execution of the drift detection pipeline: fetch reference distributions from training set → fetch current predictions/features from `prediction_log` table → compute PSI/KS for each feature → compute JS divergence on predictions → generate Evidently report → store metrics → alert if thresholds exceeded.    | Triggered by Airflow DAG (weekly, post-retraining) or ad-hoc via FastAPI endpoint. Can run independently of the retraining cycle.                                                                             |
| **Inference Log**          | Storage of all prediction requests and responses for drift monitoring. Every call to `GET /predict/{ticker}` logs: ticker, features (pre-normalised), prediction, confidence, true_label (if later available), timestamp, model_version.                                                                                         | Stored in `prediction_log` PostgreSQL table. Partitioned by month for query performance. Rows: ~100-500 per day (per-user predictions). Retention: 90 days (configurable).                                    |
| **Prediction Feature**     | The raw (pre-standardisation) feature values computed during inference. Stored alongside the prediction in `prediction_log` so drift detection can compare inference-time feature distributions against training-time reference distributions, even after the source OHLCV data has been updated (e.g. new data overwrites old). | 17 float values per prediction + timestamp. Stored as a JSONB column. This is the "current window" distribution for PSI/KS drift tests.                                                                       |
| **Reference Distribution** | The per-feature distribution computed from the training set at model training time. Captured once when the champion model is trained and stored in `model_registry` or as a standalone reference dataset in S3. Used as the baseline for all drift comparisons until the champion changes.                                       | Per-feature histograms (binned into 20 equal-frequency bins). Computed from the training set's pooled feature values across all training tickers. Stored as JSONB alongside the champion model.               |
| **Drift Metric**           | Key numeric drift indicators stored in the `drift_metrics` PostgreSQL table for queryability and dashboarding.                                                                                                                                                                                                                   | Per-entry: ticker, feature_name, drift_metric_type (PSI/KS/js_divergence), drift_score, alert_triggered (boolean), reference_period, current_period.                                                          |

### Data Flow — Weekly Retraining DAG

```
Airflow DAG (weekly)
  ├── Task 1: fetch_new_ohlcv → upsert into ohlcv_prices (via market/repository.py pattern)
  ├── Task 2: run_training → docker compose run ml python -m ml.pipeline
  │     └── → Existing pipeline: fetch 6yr OHLCV → features → train → evaluate → MLflow
  ├── Task 3: evaluate_challenger → compare vs champion (from model_registry)
  │     └── If directional_accuracy > champion + 2pp → promote
  ├── Task 4: run_drift_detection (if champion changed or weekly)
  │     └── → Fetch reference distributions from champion metadata
  │     └── → Fetch production inference logs from prediction_log table
  │     └── → Compute PSI/KS per feature per monitored ticker
  │     └── → Compute JS divergence on prediction distributions
  │     └── → Generate Evidently HTML report → upload to S3
  │     └── → Store key metrics in drift_metrics table
  │     └── → Alert if any threshold exceeded (CloudWatch metric + log)
  └── Task 5: cleanup → prune old prediction_log rows
```

### Data Flow — Drift Detection (on-demand or scheduled)

```
Trigger (DAG / API) → DriftDetector
  → Fetch reference distribution from champion model metadata
  → Fetch recent prediction_log entries (last N days, configurable)
  → For each monitored ticker:
    → Extract feature values from prediction_log
    → Compute PSI(ref_feature_dist, current_feature_dist) per feature
    → KS-test(ref_feature_dist, current_feature_dist) per feature
    → Compute prediction class distribution JS divergence
  → Generate Evidently HTML report
  → Upload to S3 → generate pre-signed URL
  → Persist key metrics to drift_metrics table
  → Log alerts for any feature with PSI>0.25 or JS>0.3
```

---

## Edge Cases & Risks

| Edge Case                                        | Handling                                                                                                                                                                                |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ticker with < 5 years of OHLCV data              | Use all available data; pad with zeros at sequence boundaries. If < 30 days + feature window (60 days total), exclude from training.                                                    |
| Unseen ticker at inference                       | Use UNK embedding vector. Result is less accurate but still functional. Log warning.                                                                                                    |
| Market regime shift (e.g., 2020 COVID crash)     | Training includes crash periods within the 5-year 6-year window, so the model learns regime-aware patterns. 5-year 6-year rolling window naturally discards pre-2021 regimes over time. |
| Model confidence is low (< 0.4)                  | Return prediction with `confidence: "low"` flag. Frontend may choose to show "uncertain" indicator or fall back to historical CAGR.                                                     |
| yfinance data for model training unavailable     | Training pipeline must verify OHLCV data exists before starting. Skip tickers with insufficient data. Log warning.                                                                      |
| MLflow server unavailable                        | Training should log to local filesystem as fallback (`mlruns/` directory). Alert in logs.                                                                                               |
| GPU unavailable (MPS/CUDA)                       | Fall back to CPU. MPS (Apple Silicon) supported via `torch.backends.mps.is_available()`. CUDA supported via `torch.cuda.is_available()`. Training is slower but functional.             |
| Simulated Sharpe has extreme values (>5 or < -5) | Cap detected — flag in evaluation report. Likely due to look-ahead bias or data leakage. Investigate chronology split integrity.                                                        |
| Inference latency (model forward pass time)      | ~5-20ms per ticker on CPU with 64-hidden LSTM. Redis cache (6h TTL) prevents repeated inference for same ticker. Model weights ~0.5MB.                                                  |
| Drift report too large (many portfolio tickers)  | Generate per-ticker sub-reports with aggregate summary. S3 stores one report per drift run, not one per ticker.                                                                         |
| Training and drift detection overlap             | Airflow DAG sequences tasks: training completes before drift detection starts. No overlap.                                                                                              |
| S3 pre-signed URL expiry                         | URLs expire in 7 days (configurable). FastAPI endpoint refreshes URL on each request.                                                                                                   |
| prediction_log table grows unbounded             | Index on `created_at`. Cron job (via Airflow cleaner task) prunes rows older than 90 days. ~300 bytes/row, ~13.5 MB/90 days at current scale.                                           |

---

## Production Deployment (Phase 5)

| Term                          | Definition                                                                                                                                                                                                                                            | Attributes / Constraints                                                                                                                                                                    |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Champion Artifact**         | The promoted model bundle (model weights `.pt` + ticker vocabulary + feature mean/std) that the serving task loads at startup. Published by the retraining DAG on each promotion.                                                                     | Stored in S3 under the `mlflow-artifacts` bucket `champion/` prefix. One champion at a time. Delivered to the task at startup, not baked into the image.                                    |
| **S3 Bootstrap**              | The startup step a serving task runs before launching the API: it downloads the Champion Artifact from S3 into the local `/model_artifacts/champion/` directory. `prediction_service.load_model` then reads the local file exactly as in development. | Runs once per task start. Fails fast (non-zero exit) if the download fails so a model-less task is never served. Reuses IAM task-role `s3:GetObject` on the champion prefix.                |
| **Prediction Result Cache**   | The Redis cache of completed `GET /predict/{ticker}` responses. Distinct from the model artifact — the cache holds inference _results_, the model is loaded once at task startup.                                                                     | 6-hour TTL (`PREDICTION_CACHE_TTL = 21600`). Same ticker within 6h returns the cached prediction. Does not change between dev and prod.                                                     |
| **Remote State**              | Terraform state stored in a versioned, encrypted S3 bucket with a DynamoDB lock table, instead of local `terraform.tfstate`. Prevents concurrent-apply corruption and state loss. Production is the only environment — no dev/staging.                | Single production state file (`stocklens/production/terraform.tfstate`). Required before the CI/OIDC deploy pipeline runs.                                                                  |
| **OIDC Deploy**               | CI/CD authentication to AWS via GitHub Actions OpenID Connect (`AssumeRoleWithWebIdentity`) — no long-lived AWS keys. The deploy pipeline runs ruff → pytest → checkov + tfsec → docker (ARM64) → ECR → terraform → ECS rolling deploy.               | Deploy role pinned to the repo + branch. Production environment requires manual approval.                                                                                                   |
| **WAF**                       | AWS WAFv2 Web ACL in front of the ALB: a rate-based rule (200 requests/minute per IP, blocking from day 1) plus managed rule groups for SQL injection and XSS. Protects the public prediction API.                                                    | Associated to the ALB. Blocks from day 1 — no metrics-only baseline phase (user directive).                                                                                                 |
| **Auto Scaling**              | ECS Fargate target-tracking scaling on two dimensions: average CPU utilisation and average request count per target. Keeps desired count between a minimum (HA) and a cost-bounded maximum.                                                           | Min 2 (AZ spread), max bounded by the realistic cost guardrail (Round 4: $120 warn / $300 hard; alert via AWS Budgets). Decoupled from model promotion — new tasks re-run the S3 bootstrap. |
| **Serving Backend**           | The inference execution target. Primary = Fargate (local `GlobalLSTM` forward pass). Alternate = SageMaker serverless endpoint, selected via `PREDICTION_SERVING_BACKEND`.                                                                            | Default `fargate` (local testing). `sagemaker` is a config-gated required path; behaviour of `/predict` is identical either way, but both must be deployed and wired.                       |
| **Phantom `BEDROCK_API_KEY`** | A secret named in earlier planning docs that does not exist and is not consumed. Bedrock is called via IAM task-role `bedrock:InvokeModel` + the `BEDROCK_MODEL_ID` plain env var.                                                                    | Removed from all plans/secrets (ADR 007). Do not create or inject it.                                                                                                                       |

---

## Conversational Finance Agent (Phase 6)

| Term                                              | Definition                                                                                                                                                                                                                                                                      | Attributes / Constraints                                                                                                                                                                                                        |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Finance Agent** (aka **LangGraph ReAct Agent**) | The LangGraph-based conversational AI implementing the **ReAct (Reason + Act)** loop — it reasons, calls tools (16 total), incorporates results, and streams responses via SSE. Answers questions about portfolio, spending, market data, and forecasts. Never executes trades. | Analytical & Professional persona. Uses LangGraph StateGraph + ToolNode (ReAct loop). Deployed as FastAPI `/agent/chat` SSE endpoint.                                                                                           |
| **Agent Graph**                                   | A LangGraph `StateGraph` that defines the agent's control flow: nodes = {agent_decision, tool_execution}, edges = conditional routing based on tool call necessity.                                                                                                             | Compiled once at startup and reused across all conversations. `State` = list of `BaseMessage` (conversation history).                                                                                                           |
| **Agent Tool**                                    | A callable function wrapping a FastAPI endpoint or data provider, registered with LangGraph via `@tool` decorator (or `StructuredTool`). Each tool has a name, description, and typed parameter schema that the LLM uses to decide when and how to call it.                     | Tool descriptions are the primary mechanism for correct tool selection — must be precise and enumerative (list what the tool CAN and CANNOT do). Descriptions follow pattern: `{what_it_does} + {when_to_use} + {limitations}`. |
| **Tool Call**                                     | An invocation of an Agent Tool by the LLM during the reasoning loop. Parameters are LLM-generated JSON matching the tool's Pydantic schema.                                                                                                                                     | Success/failure tracked per-tool for monitoring. Failed tool calls return structured error to the LLM for graceful degradation.                                                                                                 |
| **Tool Result**                                   | The data returned from a successful Tool Call. Typed as a string (LangGraph convention — serialised JSON or summary text).                                                                                                                                                      | The LLM's response must stay within tool-provided data. No hallucination beyond tool results (enforced by persona prompt).                                                                                                      |
| **Streaming Response**                            | Server-sent events (SSE) delivering tokens progressively as the agent generates its response. Uses FastAPI `StreamingResponse` + LangGraph's `astream_events()` with `version="v2"`.                                                                                            | Events: `on_chat_model_start`, `on_tool_start`, `on_tool_end`, `on_chat_model_stream` (token deltas). Frontend consumes via `EventSource` or `fetch` with `ReadableStream`.                                                     |
| **Persona Prompt**                                | The system prompt that defines the agent's personality, scope, and constraints. Loaded at graph compile time, injected as the first SystemMessage in every conversation.                                                                                                        | Analytical & Professional tone. Key directives: (a) answer only from tool data, (b) disclose limitations, (c) never hallucinate ticker/price data, (d) cite sources where possible, (e) no trade execution.                     |
| **Graceful Degradation**                          | When a tool call fails (yfinance down, missing data, invalid ticker), the agent reports what succeeded and what didn't, then provides a partial answer from available data.                                                                                                     | Implemented via error handling in each tool + instruction in persona prompt. Failed tools are retried once internally before degrading.                                                                                         |
| **Agent Conversation**                            | A single user query + the agent's full reasoning trace (tool calls, intermediate thoughts) + final response. Persisted via two-tier: Redis (hot, 7-day TTL) for fast resume, RDS `agent_conversations` table for permanent archive.                                             | All past conversations visible. No auto-deletion. Agent has full context of current conversation (within one chat session). No cross-conversation memory in v1.                                                                 |
| **Conversation Session**                          | A sequence of user messages in the same chat UI. Tied to a `user_id`. Backend treats each request independently but loads prior turns from Redis (hot) or RDS (cold) for context.                                                                                               | Defined by `conversation_id` (UUID). Created on first message. State loaded from Redis → RDS fallback on miss.                                                                                                                  |
| **Two-Tier Persistence**                          | Custom state management replacing `MemorySaver` — Redis for active session state across ECS tasks, RDS for permanent conversation history. State survives container restarts and enables horizontal scaling.                                                                    | Tier 1: Redis hash `agent:session:{id}` with 7-day TTL (refreshed per turn). Tier 2: `conversations` (metadata) + `agent_conversations` (messages) in RDS. No `langgraph-checkpoint-postgres` dependency.                       |
| **Conversations Table**                           | Lightweight RDS table for conversation listing and metadata. Avoids full message scan on the history endpoint.                                                                                                                                                                  | Columns: id (UUID PK), user_id (FK), title, message_count, created_at, updated_at. Indexed on (user_id, updated_at DESC).                                                                                                       |
| **Redis State Key**                               | Active conversation state stored as a Redis hash. Contains the serialised message list, user_id, message_count, and updated_at timestamp.                                                                                                                                       | Key format: `agent:session:{conversation_id}`. TTL: 604800s (7 days) — refreshed on every turn via `EXPIRE`.                                                                                                                    |
| **LLM-as-Judge**                                  | Periodic evaluation of live agent responses using a stronger LLM (GPT 5.4 evaluated against agent's DeepSeek V3.1). Samples a subset of production conversations and scores them on three dimensions.                                                                           | Sampling rate: configurable (default 10% of conversations). Scored offline (async background task). Results stored in `agent_evaluations` table. No impact on response latency.                                                 |
| **Answer Relevance**                              | Does the agent's final response directly answer the user's question? Scored 0–1 by the judge model.                                                                                                                                                                             | Dimension 1 of 3 in LLM-as-Judge. A response that changes the subject or ignores the question scores 0.                                                                                                                         |
| **Tool Selection Correctness**                    | Did the agent call the appropriate tool(s) for the user's question? Scored 0–1 by the judge model.                                                                                                                                                                              | Dimension 2 of 3. Wrong tool = 0 (e.g., calling `get_market_news` for a portfolio question).                                                                                                                                    |
| **Context Adherence**                             | Does the final response stay within the data returned by the tools, without introducing external information? Scored 0–1 by the judge model.                                                                                                                                    | Dimension 3 of 3. Hallucinated numbers/facts = 0.                                                                                                                                                                               |
| **Composite Relevance Score**                     | Weighted average of Answer Relevance (0.4) + Tool Selection (0.3) + Context Adherence (0.3). Used to track agent quality over time.                                                                                                                                             | Sampled from live traffic. Logged per-evaluation with judge model ID and timestamp.                                                                                                                                             |
| **Golden Evaluation Set**                         | A curated set of test questions with expected tool calls and ideal responses. Used to validate the agent after changes and to qualify new model versions.                                                                                                                       | Mix of single-tool, multi-tool, and edge case scenarios. No hard count limit (~20–30 expected). Each entry = {question, expected_tools[], expected_response_key_points[], judge_score_threshold}.                               |
| **Agent Monitoring — Latency Drift**              | Tracks response latency percentiles (p50/p95/p99) over sliding windows for agent conversations. Alerts on sustained degradation or outlier spikes.                                                                                                                              | Measured per-conversation. Window = 1h rolling. Alerts via CloudWatch if p95 > 20s for 5 consecutive windows.                                                                                                                   |
| **Agent Monitoring — Tool Success Rate**          | Per-tool invocation success rate, failure modes (timeout, parsing error, API error), and recovery actions tracked via structured logs.                                                                                                                                          | Logged in `agent_conversations.tools_used` (JSONB — includes status and error per tool call). CloudWatch metric filter on `{ $.tool_status = "error" }`.                                                                        |
| **Agent Monitoring — LLM Response Relevance**     | Periodic LLM-as-Judge relevance score sampled from live traffic. See LLM-as-Judge, Composite Relevance Score.                                                                                                                                                                   | Sampling rate configurable via `AGENT_EVAL_SAMPLE_RATE` (default 0.1). Results stored in `agent_evaluations` table.                                                                                                             |

### Data Flow — Agent Chat (Streaming) with Two-Tier Persistence

```
Client (React Native) → POST /agent/chat { message, conversation_id? }
  → FastAPI router (StreamingResponse)
  → No conversation_id → create conversations row (RDS)
  → Try Redis GET agent:session:{id} for active state        ◄── Tier 1 (hot)
  → On Redis miss → build from RDS agent_conversations       ◄── Tier 2 (cold)
  → Build Messages list: [SystemMessage(persona_prompt), *past_turns, HumanMessage(user_message)]
  → Compile LangGraph graph (once, cached at lifespan)
  → astream_events(graph, input, version="v2")
    ├── on_chat_model_start → frontend: "thinking..."
    ├── on_tool_start { tool_name, input } → frontend: tool indicator
    ├── on_tool_end { tool_name, output } → frontend: tool result summary
    └── on_chat_model_stream { chunk } → frontend: append to response text
  → After stream completes:
    → INSERT user message + assistant response into agent_conversations (RDS)
    → UPDATE conversations (message_count, updated_at) (RDS)
    → SET agent:session:{id} in Redis with 7-day TTL refresh  ◄── Hot tier updated
    → Sample for LLM-as-Judge evaluation (if random < AGENT_EVAL_SAMPLE_RATE)
```

### Data Flow — Agent Evaluation (Background)

```
Background task (after agent response):
  → If sampled (random < AGENT_EVAL_SAMPLE_RATE):
    → Build evaluation prompt: { question, agent_trace, response }
    → Call judge model (GPT 5.4 — stronger than agent's DeepSeek V3.1)
    → Score: answer_relevance (0–1), tool_selection (0–1), context_adherence (0–1)
    → Compute composite: 0.4 × answer_relevance + 0.3 × tool_selection + 0.3 × context_adherence
    → Store in agent_evaluations table
    → Log structured metric to CloudWatch (composite_relevance_score)
```

### Architecture — LangGraph StateGraph

```
Graph Definition (compiled at startup):

  State = {
    messages: list[BaseMessage],   // conversation history + new input
    tool_calls: list[dict],         // track tool invocations for monitoring
  }

  Nodes:
    [agent] → LLM decides: respond directly or call a tool
    [tools] → Execute the tool requested by the LLM, return result

  Edges:
    agent → tools (if tool call requested)
    agent → end (if final response ready)
    tools → agent (tool result → LLM continues reasoning)

  Entry Point: agent
  End Condition: agent produces AIMessage with no tool calls
```

### Tool Inventory (Phase 6)

**16 tools** (reduced from 19 after review — see `docs/goal_tool_review.md` for cuts/merges. `get_cash_flow_summary` was flagged as potentially redundant but kept — it shows deposit/withdrawal patterns over time, distinct from `get_portfolio_summary`'s current cash balance snapshot):

| Category        | Tools                                                                        | Data Source Notes                                                    |
| --------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **Market Data** | `get_market_ohlcv`, `get_market_quote`, `get_ticker_info`, `get_market_news` | yfinance — news has limited/stale data ⚠️                            |
| **Portfolio**   | `get_portfolio_summary`, `get_portfolio_holdings`, `get_sector_exposure`     | Sector exposure is NEW (yfinance ticker→sector map)                  |
| **Performance** | `get_portfolio_performance` (merged with history), `compare_to_benchmark`    | `include_history` param on performance                               |
| **Forecasting** | `get_lstm_forecast`                                                          | Existing prediction service                                          |
| **Spending**    | `get_spending_analysis`, `get_recent_transactions`, `get_cash_flow_summary`  | Spending analysis is NEW — may replace raw transactions for spend Qs |
| **Analysis**    | `get_portfolio_diversification_score`, `compare_tickers_side_by_side`        | Both NEW — HHI diversification is top differentiator                 |
| **Insights**    | `get_dividend_insights`                                                      | NEW — yfinance dividend fields                                       |

**Cut from v1:** `get_ticker_screening` (no yfinance screening API), `get_drift_metrics` (MLOps metric, not user-facing), `get_portfolio_history` (merged into performance).
