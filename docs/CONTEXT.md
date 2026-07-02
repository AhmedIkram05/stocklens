# StockLens — Domain Glossary

> **Purpose:** Shared vocabulary across all phases. Updated per-phase.
> **Audience:** AI coding agents implementing any phase.
> **All terms defined here are normative** — if implementation docs use different language, this glossary wins.

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

| Term                       | Definition                                                                                                                                                                | Attributes / Constraints                                                                                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Directional Forecast**   | The model's prediction: UP (price will rise), FLAT (price will stay within noise band), DOWN (price will fall).                                                           | 3-class classification. Confidence ∈ [0, 1] for each class.                                                                                                                          |
| **Global Model**           | A single LSTM trained on 50+ S&P 500 components simultaneously, with ticker entity embeddings to learn ticker-specific patterns. Generalizes to unseen tickers via UNK.   | One model with one MLflow run. Not per-ticker models.                                                                                                                                |
| **Feature Window**         | The 30-trading-day lookback window used to construct each prediction sample. Each sample is 30 rows × N_features.                                                         | Fixed at 30 trading days (not calendar days). Defined in both the dataset generator and the model's input layer.                                                                     |
| **Technical Indicators**   | The feature set computed from raw OHLCV for each ticker: log returns (1d, 5d, 21d), moving averages (5, 10, 20, 50-day), RSI(14), MACD(12,26,9), rolling volatility(30d). | All computed from `adjusted_close`. Standardised per ticker (z-score) across the training window. NaN-padded at sequence boundaries.                                                 |
| **Log Returns**            | `ln(P_t / P_{t-1})` — the standard transform for financial time series. Used as the primary return metric for labeling and feature engineering.                           | Daily log returns. Multi-period: 1d, 5d, 21d log returns included as features.                                                                                                       |
| **Adaptive Label**         | The UP/FLAT/DOWN label computed using a rolling volatility threshold, not a fixed percentage.                                                                             | `FLAT` if `                                                                                                                                                                          | log_return | < 0.5 × σ_30d`. `UP`if`log_return ≥ 0.5 × σ_30d`. `DOWN`if`log_return ≤ −0.5 × σ_30d`. `σ_30d` = rolling 30-day standard deviation of daily log returns. |
| **Entity Embedding**       | A learned vector representation per ticker, used by the Global Model to capture ticker-specific price dynamics while keeping the LSTM weights shared across all tickers.  | Vocabulary = all training tickers + UNK token. Embedding dimension = 16 (configurable). UNK embedding is learned for unseen tickers.                                                 |
| **Champion Model**         | The best-performing registered model in MLflow (by directional accuracy on validation set). Promoted via MLflow Model Registry aliases.                                   | Stored in `model_registry` DB table with alias='champion'. One champion at a time.                                                                                                   |
| **MLflow Run**             | A single training execution, logged with hyperparameters, loss curves, confusion matrix, evaluation metrics, and the model artifact.                                      | Runs stored in the MLflow tracking server (Docker Compose service) with SQLite backend.                                                                                              |
| **Directional Accuracy**   | Percentage of correct direction predictions across all test samples. Not just UP accuracy — all 3 classes.                                                                | Computed on the held-out test set (last 15% chronological).                                                                                                                          |
| **Simulated Sharpe**       | Sharpe ratio from a signal-based trading simulation: long the ticker when model predicts UP, flat (cash) when FLAT or DOWN.                                               | Daily returns from the simulated strategy. `Sharpe = mean(daily_return) / std(daily_return) × sqrt(252)`. No transaction costs in V1 (ponytail: add if live trading is implemented). |
| **Chronological Split**    | Train/validation/test split that respects time ordering: earliest 70% of trading days → train, next 15% → validation, last 15% → test. No random shuffle.                 | Applied globally after merging all tickers' data. Each sample stays in its time bucket based on the last date in its feature window.                                                 |
| **Weighted Cross-Entropy** | Cross-entropy loss with class weights inversely proportional to class frequencies. Handles UP/FLAT/DOWN imbalance where FLAT dominates.                                   | `class_weight[c] = total_samples / (n_classes × samples_in_class[c])`. Weights computed per training epoch over the current ticker subset.                                           |

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
backend/ml/train.py
  1. Fetch OHLCV for 50+ S&P 500 tickers + portfolio tickers from ohlcv_prices (ensure 5yr rolling window data)
  2. Compute features + labels per ticker
  3. Build ticker vocabulary → assign embedding indices
  4. Merge all tickers into global dataset (chronological ordering)
  5. Chronological split: train 70% / val 15% / test 15%
  6. Create DataLoaders with SequenceDataset
  7. Initialise GlobalLSTM model (vocab_size, embed_dim=16, hidden=128, n_layers=2, dropout=0.3, n_features)
  8. Train with Adam, weighted cross-entropy, early stopping (patience 10)
  9. Evaluate on test set: directional accuracy, per-class F1, confusion matrix, Simulated Sharpe
  10. Log everything to MLflow (tracking server at http://mlflow:5000)
  11. Register champion model in MLflow Model Registry + persist to model_registry DB
```

### Model Architecture (torch.nn.Module)

```
GlobalLSTM(
  ticker_embedding: Embedding(vocab_size, embed_dim=16, padding_idx=UNK)
  feature_projection: Linear(N_features, hidden_dim)
  lstm: LSTM(hidden_dim, hidden_size=128, num_layers=2, dropout=0.3, batch_first=True)
  classifier: Linear(128, 3) → softmax
)
```

---

## Edge Cases & Risks (Phase 3+)

| Edge Case                                        | Handling                                                                                                                                                                    |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ticker with < 5 years of OHLCV data              | Use all available data; pad with zeros at sequence boundaries. If < 30 days + feature window (60 days total), exclude from training.                                        |
| Unseen ticker at inference                       | Use UNK embedding vector. Result is less accurate but still functional. Log warning.                                                                                        |
| Market regime shift (e.g., 2020 COVID crash)     | Training includes crash periods within the 5-year window, so the model learns regime-aware patterns. 5-year rolling window naturally discards pre-2021 regimes over time.   |
| Model confidence is low (< 0.4)                  | Return prediction with `confidence: "low"` flag. Frontend may choose to show "uncertain" indicator or fall back to historical CAGR.                                         |
| yfinance data for model training unavailable     | Training pipeline must verify OHLCV data exists before starting. Skip tickers with insufficient data. Log warning.                                                          |
| MLflow server unavailable                        | Training should log to local filesystem as fallback (`mlruns/` directory). Alert in logs.                                                                                   |
| GPU unavailable (MPS/CUDA)                       | Fall back to CPU. MPS (Apple Silicon) supported via `torch.backends.mps.is_available()`. CUDA supported via `torch.cuda.is_available()`. Training is slower but functional. |
| Class imbalance in adaptive labeling             | Weighted cross-entropy handles this. Monitor per-class F1 after training — retune threshold multiplier (0.5 × σ_30d) if minority classes collapse.                          |
| Simulated Sharpe has extreme values (>5 or < -5) | Cap detected — flag in evaluation report. Likely due to look-ahead bias or data leakage. Investigate chronology split integrity.                                            |
| Inference latency (model forward pass time)      | ~10-50ms per ticker on CPU with 128-hidden LSTM. Redis cache (6h TTL) prevents repeated inference for same ticker. Model weights ~2MB (fairly small).                       |
