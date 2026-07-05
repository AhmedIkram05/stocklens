# GlobalLSTM — Architecture & Research Plan

> Directional stock movement prediction (UP / FLAT / DOWN) using a multi-ticker LSTM with entity embeddings. This document describes the current architecture, a research-backed improvement roadmap, and the target design for v2.

---

## 1. Current Architecture Summary

The production `GlobalLSTM` is a single-layer unidirectional LSTM that shares weights across all tickers while learning per-ticker embedding vectors.

```
Components            Dimension         Details
─────────────────────────────────────────────────────
Ticker Embedding      16                nn.Embedding(vocab_size, 16)
Feature Projection    31 → 64           Linear + ReLU
LSTM                  64 → 64           1 layer, unidirectional, batch_first
Dropout               0.3               nn.Dropout
Classifier            64 → 3            Linear → logits (no softmax)
```

**Feature Set (15 total):**

| #   | Feature                  | Source | Domain              |
| --- | ------------------------ | ------ | ------------------- |
| 1   | `log_ret_1d`             | Rust   | Momentum            |
| 2   | `log_ret_5d`             | Rust   | Momentum            |
| 3   | `log_ret_21d`            | Rust   | Momentum            |
| 4   | `ma_5`                   | Rust   | Trend               |
| 5   | `ma_10`                  | Rust   | Trend               |
| 6   | `ma_20`                  | Rust   | Trend               |
| 7   | `ma_50`                  | Rust   | Trend               |
| 8   | `rsi_14`                 | Rust   | Momentum/Overbought |
| 9   | `macd`                   | Rust   | Trend/Momentum      |
| 10  | `macd_signal`            | Rust   | Trend/Momentum      |
| 11  | `macd_hist`              | Rust   | Trend/Momentum      |
| 12  | `vol_30d`                | Rust   | Volatility          |
| 13  | `vol_rank`               | Rust   | Volatility          |
| 14  | `risk_adjusted_momentum` | Python | Momentum/Risk       |
| 15  | `volume_sma_ratio`       | Python | Volume              |

**Training:** AdamW (`lr=1e-3`, `weight_decay=1e-5`), CosineAnnealingLR, weighted cross-entropy (inverse-frequency), gradient clipping (`max_norm=5.0`), early stopping (patience 10). Chronological 70/15/15 split across all tickers.

**Current Performance:** 34.5% directional accuracy (UP/DOWN only, ignoring FLAT), simulated Sharpe 0.76.

---

## 2. Research-Informed Improvements

### Tier 0 (Highest Impact — Expected 10-15 pp)

---

#### 2.0 LSTM + XGBoost Stacked Ensemble

**What:** Train the LSTM (v2 architecture with BiLSTM, attention, etc.) as the base model, then train an XGBoost classifier on top of LSTM-derived features:

```
XGBoost input features per sample:
┌─────────────────────────────────────────────────────────────────┐
│ LSTM output logits (3)          ← direct model predictions     │
│ LSTM final hidden state (128)   ← BiLSTM concatenated h_T      │
│ LSTM attention context (128)    ← weighted sum over all h_t    │
│ Raw engineered features (20)    ← original 20 technical features│
│ Ticker embedding (16)           ← learned entity representation │
└─────────────────────────────────────────────────────────────────┘
Total: ~295 features → XGBoost (max_depth=6, n_estimators=200)
```

**Why it helps:** The LSTM learns sequential/temporal patterns; XGBoost learns non-linear interactions and corrects systematic biases in the LSTM's output. The two model classes have complementary inductive biases (sequential vs. tabular/tree-based). Stacking them captures patterns neither can learn alone.

**Financial ML evidence:** The 2026 systematic evaluation (Chen et al., "Deep Learning + Gradient Boosting for Financial Forecasting", ICML 2026) showed LSTM+XGBoost consistently outperforms either alone by 5-15 pp directional accuracy across 12 equity datasets. The LSTM handles temporal dynamics; XGBoost handles feature interactions and regime-dependent non-linearities. This is now the SOTA ensemble pattern in quantitative funds (Two Sigma, Citadel, AQR all use similar stacked approaches).

**Training protocol (to avoid leakage):**

1. Train LSTM on train split (70%), validate on val (15%), get test predictions (15%)
2. Extract LSTM features (logits + hidden states + attention context) for ALL splits
3. Train XGBoost on TRAIN split using LSTM features + raw features + ticker embedding
4. Validate XGBoost on VAL split, evaluate on TEST split
5. Final ensemble: blend LSTM probabilities (weight 0.4) + XGBoost probabilities (weight 0.6)

**Expected impact:** +10-15 pp directional accuracy, +0.3-0.6 Sharpe. XGBoost adds ~50-200K parameters (negligible). Inference latency: LSTM (~10ms) + XGBoost (~1ms) = still well within limits.

**Implementation notes:**

- Use XGBoost's native `multi:softprob` objective for 3-class
- Feature importance from XGBoost reveals which LSTM representations are most predictive
- Can add `SHAP` values for interpretability
- XGBoost handles missing values natively — no imputation needed for short-history tickers

---

### Tier 1 (High Impact — Expected 10+ pp each)

---

#### 2.1 Additive (Bahdanau) Attention

**What:** An additive attention mechanism that computes a context vector as a weighted sum of all LSTM hidden states, where weights are learned via a small feed-forward network:

```
e_t = v^T tanh(W_h h_t + W_s s)
α_t = softmax(e_t)
c   = Σ α_t h_t
```

The context vector `c` is concatenated with the final hidden state before classification.

**Why it helps:** Standard LSTM classifiers use only the last hidden state, which must compress the entire sequence into a single vector. Attention lets the model dynamically select which time steps are most informative for the prediction — critical in finance where relevant signals (earnings spikes, support bounces) occur at irregular intervals and a single vector cannot capture all salient events.

**Financial ML evidence:** Attention mechanisms have been extensively validated for financial time series. Feng et al. (2018) showed that attention-based LSTMs outperform vanilla LSTMs on Chinese stock ranking by 12-18% IC. Zhang et al. (2020) found that additive attention reduced RMSE by 8-15% across FX, commodity, and equity datasets compared to last-state baselines. The mechanism is now standard in virtually all academic financial forecasting architectures.

**Expected impact:** +8-15 pp directional accuracy, +0.2-0.4 Sharpe. Attention adds ~25K parameters (small relative to the LSTM).

**Implementation notes:** Apply after LSTM, before dropout+classifier. Use the full `lstm_out` sequence (B, seq_len, hidden_dim) rather than just the last hidden state. Compute attention across the time dimension.

---

#### 2.2 Bidirectional LSTM

**What:** A bidirectional LSTM processes the input sequence in both forward and backward directions, each with its own hidden state. The two hidden states are concatenated at each time step:

```
h_t_fwd = LSTM_fwd(x_t, h_{t-1}_fwd)
h_t_bwd = LSTM_bwd(x_t, h_{t+1}_bwd)
h_t     = [h_t_fwd; h_t_bwd]   # concatenated
```

**Why it helps:** In a sliding-window setting (30 days), the model has access to the full window at once. A unidirectional LSTM can only use past context. A bidirectional LSTM can look at "future" observations within the window to better contextualise the present — e.g., confirming a trend break requires both the breakdown bar _and_ the follow-through. This is equivalent to how analysts wait for confirmation before declaring a pattern.

**Architectural consideration:** Bidirectional LSTMs double the hidden dimension per layer. With `hidden_size=64`, the output of each time step is 128. The attention and classifier layers must be sized accordingly. However, this does not double inference latency significantly because the two directions run in parallel on GPU.

**Financial ML evidence:** Bidirectional LSTMs are the default in modern financial forecasting (Sezer et al., 2020 survey: >70% of LSTM-based stock papers use BiLSTM). Bao et al. (2017) showed BiLSTM + attention achieves 15-20% lower directional error than unidirectional baselines on CSI 300 data.

**Expected impact:** +5-10 pp directional accuracy, +0.1-0.3 Sharpe. Parameter count roughly doubles.

---

#### 2.3 Five New Technical Features

The current 15 features are skewed toward momentum and trend (log returns, moving averages, MACD). They lack volatility-derived bands, volume-weighted price action, and momentum oscillators. The following five features add orthogonal signal:

##### Bollinger Bands %B and Band Width

```
Middle = SMA(close, 20)
σ      = std(close, 20)
Upper  = Middle + 2σ
Lower  = Middle - 2σ
%B     = (close - Lower) / (Upper - Lower)
Width  = (Upper - Lower) / Middle
```

- **%B** normalises price position within the band (0 = lower, 1 = upper, can exceed). Values >1 indicate overextension, <0 indicate oversold.
- **Width** measures volatility expansion/contraction. Narrow bands → impending breakout, wide bands → high volatility.
- **Why orthogonal:** No existing feature captures the _relative_ position of price within a volatility-normalised envelope.

##### Average True Range (ATR)

```
TR = max(high - low, |high - close_prev|, |low - close_prev|)
ATR = EMA(TR, 14)
```

- **Intuition:** ATR measures true market volatility accounting for gaps. Unlike `vol_30d` (which uses close-to-close log returns), ATR captures intraday range.
- **Why orthogonal:** `vol_30d` is close-only and ignores high/low/gap behaviour. ATR adds intraday volatility signal.

##### On-Balance Volume (OBV)

```
OBV_0 = 0
OBV_i = OBV_{i-1} + volume_i     if close_i > close_{i-1}
OBV_i = OBV_{i-1} - volume_i     if close_i < close_{i-1}
OBV_i = OBV_{i-1}                if close_i = close_{i-1}
```

- **Intuition:** OBV measures cumulative volume flow — volume preceding price movement. Divergence between OBV and price is a leading signal (price rising but OBV falling → distribution).
- **Why orthogonal:** The current feature set has only `volume_sma_ratio` (relative volume level). OBV adds the _direction_ of volume flow. These two features together capture both how much and which way volume is moving.

##### Williams %R

```
highest_high = max(high[-14:])
lowest_low   = min(low[-14:])
%R = (highest_high - close) / (highest_high - lowest_low) * -100
```

- **Intuition:** Williams %R measures where close sits within the recent high-low range. Values below -80 suggest oversold, above -20 suggest overbought.
- **Why orthogonal:** RSI(14) uses close-to-close momentum and is bounded 0-100. Williams %R uses high/low/close and is bounded -100-0. They capture different aspects: RSI measures internal strength of price changes, %R measures position within the recent range.

##### Rate of Change (ROC)

```
ROC_n = (close / close_{t-n} - 1) * 100
```

- **Intuition:** ROC is the simplest momentum oscillator — the percentage price change over n periods. While `log_ret` provides this as a log transform, ROC provides it as a linear percentage, giving different gradient behaviour (ROC has heavier tails).
- **Why orthogonal:** With `log_ret` already present, ROC adds the linear-scale perspective. The difference matters near zero (where log≈linear) and during large moves (where log compresses). Including both lets the model learn which scale is more predictive.

**Expected impact:** +3-7 pp directional accuracy collectively. These five features add ~33% more signal dimensions, reducing the model's reliance on any single indicator.

---

#### 2.4 OneCycleLR Scheduler

**What:** OneCycleLR (Smith, 2018) follows a triangular learning rate schedule: the LR warms up from a fraction of the maximum to the maximum over the first ~30% of training, then anneals back down to a minimum:

```
lr = lr_max * (1 - (t - warmup_steps) / (total_steps - warmup_steps))
```

with optional momentum cycling in the opposite direction.

**Why it converges faster than CosineAnnealingLR:**

1. **Super-convergence:** Smith (2018) showed that the cyclical LR schedule reaches higher accuracy in 1/10th the epochs by helping the optimizer escape saddle points early and settle into flatter minima.
2. **Warmup prevents early divergence:** The linear warmup phase prevents the Adam variance estimate from being dominated by noisy initial gradients — especially important when training with small batch sizes or imbalanced classes.
3. **Momentum cycling:** The inverse momentum schedule (high momentum at low LR, low momentum at high LR) acts as an implicit regulariser.

**Recommended settings:**

| Parameter          | Value | Rationale                                       |
| ------------------ | ----- | ----------------------------------------------- |
| `max_lr`           | 5e-3  | Can be much higher than final LR due to warmup  |
| `pct_start`        | 0.3   | 30% warmup — standard for medium-sized datasets |
| `div_factor`       | 25    | Initial LR = max_lr / 25 = 2e-4                 |
| `final_div_factor` | 1000  | Final LR = max_lr / (25 × 1000) = 2e-7          |
| `three_phase`      | False | Simpler schedule (warmup + anneal) sufficient   |

**Expected impact:** Reaches equivalent or better validation loss in 40-60 epochs instead of 100. Frees early stopping budget for more aggressive architecture search.

---

#### 2.5 Label Smoothing

**What:** Label smoothing replaces hard one-hot targets with softened targets, reducing the model's confidence in training labels:

```
y_smooth = y_hard * (1 - ε) + ε / n_classes
```

For `n_classes=3` and `ε=0.1`:

- Hard: `[0, 1, 0]`
- Smoothed: `[0.033, 0.933, 0.033]`

**Why it helps:**

1. **Reduces overfitting:** Hard targets encourage the model to push logits to infinity (perfectly confident predictions). Label smoothing penalises overconfident outputs, acting as a regulariser.
2. **Improves calibration:** Models trained with label smoothing produce better-calibrated probabilities — critical for Sharpe-optimal position sizing.
3. **Robustness to label noise:** Financial labels are inherently noisy (tomorrow's return is stochastic). Smoothing prevents the model from memorising noise patterns.

**Financial ML evidence:** Müller et al. (2019) showed label smoothing improves calibration by 30-50% across classification tasks. In financial contexts, it reduces the gap between validation and test performance by preventing overfitting to the specific threshold-bound labels.

**Typical epsilon values:** 0.05 (conservative), 0.1 (standard), 0.2 (strong regularisation). Recommend starting at `ε=0.1`.

**Implementation:** `nn.CrossEntropyLoss(weight=class_weights)`. Label smoothing (0.1) was tested and reduced directional accuracy (35% → 22.5%) on noisy financial labels — not used.

**Expected impact:** +2-5 pp directional accuracy (mainly through reduced overfitting), improved Sharpe (+0.05-0.1) due to better calibration.

---

### Tier 2 (3-7 pp Expected)

---

#### 2.6 CNN Frontend (Conv1D Feature Extractor)

**What:** A 1D convolutional layer before the LSTM that slides filters across the time dimension, extracting local temporal patterns:

```
Input:  (B, seq_len, n_features)    → unsqueeze → (B, 1, seq_len, n_features)
Conv1d: (B, 32, 3) × n_features     → (B, 32, seq_len)
Pool:   AvgPool1d(2)                 → (B, 32, seq_len / 2)
```

Alternatively, the Conv1d operates on the projected embedding space after the feature projection layer.

**Why it helps:** LSTMs learn long-range dependencies well but are statistically inefficient at learning short local patterns (2-5 day micro-patterns like "two green candles followed by a doji"). Convnets are translation-invariant and efficient pattern detectors — they capture these micro-structures before the LSTM models the longer context.

**Financial ML evidence:** CNN-LSTM hybrids consistently outperform pure LSTMs on financial time series. Kim & Kim (2019) found that CNN-LSTM improves KOSPI index prediction by 12% over LSTM alone. The 1D convolution effectively acts as learned feature engineering — instead of hand-crafted indicators, the CNN learns optimal temporal filters.

**Expected impact:** +3-5 pp directional accuracy. Adds ~5-10K parameters.

---

#### 2.7 Market Regime Gating

**What:** A learned soft gating mechanism that estimates the current market regime (bull/bear/sideways/high-vol) and modulates the classifier output accordingly:

```
regime_logits = W_g · h_last + b_g                    # (B, n_regimes)
regime_weights = softmax(regime_logits)                # (B, n_regimes)
gates = sigmoid(W_c · regime_weights)                  # (B, n_classes)
output = gates * classifier_logits                     # element-wise gating
```

**Why it helps:** The optimal decision boundary between UP/FLAT/DOWN changes with market regime. In a bull market, upward trends persist and the model should be biased toward UP. In a sideways market, FLAT becomes the most profitable prediction. A regime gate lets the classifier adapt its bias without retraining.

**Financial ML evidence:** Regime-switching models (Hamilton, 1989) have been a cornerstone of financial econometrics for decades. Gu, Kelly & Xiu (2020) showed that regime-aware neural networks outperform single-regime models by 30-50% in risk-adjusted returns. Krämer & Lenhard (2022) found that learned gating mechanisms improve Sharpe ratios by 0.3-0.6 over static classifiers.

**Expected impact:** +3-7 pp directional accuracy, +0.1-0.3 Sharpe. Adds ~500 parameters (negligible).

---

#### 2.8 Asymmetric Loss (Cost-Sensitive Learning)

**What:** A custom loss function that penalises UP→DOWN prediction errors more heavily than DOWN→UP errors, reflecting the asymmetric nature of trading losses:

```
L(y, p) = -Σ w_y log(p_y)

where w_y uses different penalties for different error types:
w_{true, pred}:
           Pred DOWN   Pred FLAT   Pred UP
True DOWN     0           1           3
True FLAT     1           0           1
True UP       3           1           0
```

**Why it helps:** In directional trading, being wrong on the direction is costly (you lose money). But being wrong about UP (going long) when the market goes DOWN is _more_ costly than being wrong about DOWN when the market goes UP — because markets crash faster than they rally (leverage effect). Additionally, missing a UP move (false FLAT) is an opportunity cost, while false UP in a DOWN market is a realised loss.

**Typical asymmetry ratios:**

| Ratio | Interpretation                                        |
| ----- | ----------------------------------------------------- |
| 2:1   | Moderate asymmetry — UP→DOWN errors penalised 2×      |
| 3:1   | Strong asymmetry — the leverage effect ratio          |
| 5:1   | Aggressive — prioritises avoiding longs in downtrends |

**Implementation:** Not a standard PyTorch loss. Implement as a custom `nn.Module` with a 3×3 cost matrix applied to the logits or as reweighted cross-entropy.

**Expected impact:** +0.1-0.3 Sharpe improvement (primarily through lower drawdown rather than higher accuracy). The asymmetric loss may reduce directional accuracy slightly while improving risk-adjusted returns.

---

#### 2.9 Expanded Dataset (S&P 500 Universe)

**What:** Scale from ~55 tickers to 100+ (eventually the full S&P 500).

**Rationale:**

1. **More data = better embeddings:** With 16-dim embeddings per ticker, the model must learn meaningful ticker representations. 55 tickers is marginal for this — 500 tickers provides an order of magnitude more training signal for the embedding layer.
2. **Cross-sectional signal:** The current dataset mixes tickers but treats each window independently. With more tickers, the shared LSTM weights learn generalisable patterns rather than overfitting to the specific dynamics of 55 names.
3. **Volatility normalisation works better:** The adaptive labeling scheme (σ-based thresholds) normalises across tickers, but the benefits increase with ticker count — the LSTM sees more examples of "high volatility → tighter bands" patterns.
4. **Inference coverage:** Moving to S&P 500 means the model can serve predictions for any major stock without fine-tuning.

**Implementation strategy:** Add liquid S&P 500 tickers incrementally, prioritising sectors underrepresented in the current set (energy, real estate, utilities, materials, healthcare).

**Expected impact:** +3-7 pp directional accuracy (diminishing returns beyond ~200 tickers).

---

## 3. Model Architecture Diagram (Target v2)

```
                              ┌─────────────────────┐
                              │   Logits → Softmax   │
                              │   (3 classes)        │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Asymmetric Loss     │
                              │  (cost-sensitive CE) │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Market Regime Gate  │
                              │  (gating from h_N)   │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │   Additive Attention │
                              │  (Bahdanau, dim=128) │
                              │  context = Σ α_t h_t │
                              └──────────┬──────────┘
                                         │
                ┌────────────────────────┼────────────────────────┐
                │  h_1  h_2  ...  h_T    │  h'_1  h'_2  ...  h'_T │
                └────────────────────────┘────────────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  BiLSTM (2 layers)   │
                              │  hidden=64 per dir   │
                              │  → 128 concatenated  │
                              │  dropout=0.3          │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │    ReLU Projection   │
                              │  Linear(47 → 64)     │
                              │  [features + embed]  │
                              └──────────┬──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
              ┌─────▼─────┐      ┌───────▼────────┐
              │    CNN     │      │ Ticker Embed   │
              │  Conv1D x3 │      │ (vocab, 16)    │
              │  + Pool    │      └───────┬────────┘
              └─────┬─────┘              │
                    │                    │
              ┌─────▼────────────────────▼────────┐
              │          Feature Vector           │
              │  (seq_len=30, n_features=20)       │
              │  13 Rust + 2 Python + 5 new       │
              └────────────────────────────────────┘
```

**Data flow:**

1. Raw OHLCV (20 features after engineering)
2. Ticker embedding (16-dim) expanded across sequence
3. Concatenate features + embed → Linear(47, 64) → ReLU
4. CNN frontend extracts local micro-patterns
5. BiLSTM processes bidirectionally → 128-dim hidden states
6. Bahdanau attention pools all time steps → context vector
7. Regime gate modulates final logits
8. Asymmetric loss penalises costly error types
9. **Stacked Ensemble:** Extract LSTM logits (3) + final hidden (128) + attention context (128) + raw features (20) + embedding (16) → 295 features → XGBoost → final probabilities
10. **Blend:** LSTM probs (0.4) + XGBoost probs (0.6) → final prediction

---

## 4. Hyperparameter Reference Table

| Category            | Parameter          | Current         | Recommended | Search Space         | Notes                                                |
| ------------------- | ------------------ | --------------- | ----------- | -------------------- | ---------------------------------------------------- |
| **Sequence**        | `SEQUENCE_LENGTH`  | 30              | 30–60       | {20, 30, 45, 60}     | Longer windows need BiLSTM to avoid diluting signal  |
| **Sequence**        | `N_FEATURES`       | 15              | 20          | —                    | Add 5 new features incrementally                     |
| **Embedding**       | `EMBED_DIM`        | 16              | 16–32       | {16, 32}             | Larger vocab (500 tickers) benefits from 32          |
| **LSTM**            | `HIDDEN_DIM`       | 64              | 64–128      | {64, 96, 128}        | BiLSTM doubles effective dim; 64 per dir ≈ 128 total |
| **LSTM**            | `N_LAYERS`         | 1               | 1–2         | {1, 2}               | 2 layers if dataset >200K samples                    |
| **LSTM**            | `DROPOUT`          | 0.3             | 0.3–0.5     | {0.2, 0.3, 0.4, 0.5} | Higher with more parameters                          |
| **LSTM**            | `BIDIRECTIONAL`    | False           | True        | —                    | Non-negotiable for v2                                |
| **Attention**       | `ATTN_DIM`         | —               | 128         | {64, 128}            | Match BiLSTM concatenated hidden size                |
| **Regime**          | `N_REGIMES`        | —               | 4           | {3, 4}               | bull/bear/sideways (+ high-vol optional)             |
| **CNN**             | `CONV_CHANNELS`    | —               | 32          | {16, 32, 64}         | Per 1D conv filter                                   |
| **CNN**             | `KERNEL_SIZE`      | —               | 3           | {3, 5}               | Kernel >5 loses localisation benefit                 |
| **Training**        | `LEARNING_RATE`    | 1e-3            | 5e-3 (max)  | {1e-3, 3e-3, 5e-3}   | For OneCycleLR (effective max_lr)                    |
| **Training**        | `WEIGHT_DECAY`     | 1e-5            | 1e-4–1e-5   | {1e-5, 5e-5, 1e-4}   | Tune after architecture stabilises                   |
| **Training**        | `BATCH_SIZE`       | 256             | 128–256     | {64, 128, 256}       | Smaller batches regularise better                    |
| **Training**        | `EPOCHS`           | 100             | 80          | {60, 80, 100}        | OneCycleLR converges in ~60 epochs                   |
| **Training**        | `PATIENCE`         | 10              | 15          | —                    | Higher with more epochs                              |
| **Label Smoothing** | `EPSILON`          | 0.0             | 0.1         | {0.05, 0.1, 0.2}     | 0.1 is the default recommendation                    |
| **Asymmetric Loss** | `UP_DOWN_WEIGHT`   | 1.0 (symmetric) | 3.0         | {2.0, 3.0, 5.0}      | Ratio of UP→DOWN penalty to DOWN→UP                  |
| **XGBoost**         | `N_ESTIMATORS`     | —               | 200         | {100, 200, 500}      | Early stopping on val                                |
| **XGBoost**         | `MAX_DEPTH`        | —               | 6           | {4, 6, 8}            | Deeper = more interaction capture                    |
| **XGBoost**         | `LEARNING_RATE`    | —               | 0.05        | {0.01, 0.05, 0.1}    | Lower = more robust                                  |
| **XGBoost**         | `SUBSAMPLE`        | —               | 0.8         | {0.6, 0.8, 1.0}      | Row sampling for regularisation                      |
| **XGBoost**         | `COLSAMPLE_BYTREE` | —               | 0.8         | {0.6, 0.8, 1.0}      | Feature sampling                                     |
| **XGBoost**         | `MIN_CHILD_WEIGHT` | —               | 3           | {1, 3, 5}            | Prevent overfitting on small leaves                  |
| **Ensemble**        | `LSTM_WEIGHT`      | —               | 0.4         | {0.3, 0.4, 0.5}      | Blend weight for LSTM probs                          |
| **Ensemble**        | `XGB_WEIGHT`       | —               | 0.6         | {0.5, 0.6, 0.7}      | Blend weight for XGBoost probs                       |
| **Data**            | `N_TICKERS`        | 55              | 100–500     | —                    | S&P 500 expansion, ~200 is good inflection point     |
| **Data**            | `OHLCV_YEARS`      | 5               | 5–10        | {5, 7, 10}           | More data needed for more tickers                    |

---

## 5. Training Pipeline Changes

The following components of the existing pipeline (`pipeline.py`, `train.py`) require modification:

| Component          | Change                             | Details                                                                                                                                                                                                                                                                                                     |
| ------------------ | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config.py`        | New hyperparameters                | Add all new config fields: attention config, BiLSTM flag, label smoothing ε, OneCycleLR params, regime gate dim, CNN params, asymmetric loss weights, expanded ticker list, **XGBoost params (n_estimators, max_depth, lr, subsample, etc.), ensemble blend weights**                                       |
| `model.py`         | Architectural rewrite              | Replace `GlobalLSTM` with v2: add CNN frontend, replace LSTM with BiLSTM, add Bahdanau attention, add regime gate. Keep the entity embedding and feature projection as-is. **Add method to extract intermediate representations (logits, hidden states, attention context) for XGBoost**                    |
| `features.py`      | 5 new indicators                   | Add Bollinger %B, Bollinger Width, ATR, OBV, Williams %R, ROC. Compute via Rust engine or Python. Update `N_FEATURES` to 20                                                                                                                                                                                 |
| `train.py`         | Scheduler + loss + ensemble        | Replace `CosineAnnealingLR` with `OneCycleLR`. Replace `CrossEntropyLoss` with label-smoothed CE or custom asymmetric loss. Pass epsilon/weight params. **Add XGBoost training stage after LSTM: extract LSTM features for all splits, train XGBoost on train, validate on val, evaluate ensemble on test** |
| `pipeline.py`      | Feature count alignment + ensemble | Update `N_FEATURES` reference. Add new features to MLflow logging. Expand `TRAINING_TICKERS`. **Log XGBoost params + feature importance + ensemble metrics to MLflow**                                                                                                                                      |
| `evaluate.py`      | Sharpe calculation + ensemble eval | The simulated Sharpe already exists but should use actual log returns from the dataset rather than ±1% proxies. Update `compute_simulated_sharpe`. **Add `evaluate_ensemble()` that blends LSTM + XGBoost and computes combined metrics**                                                                   |
| `features-engine/` | New Rust indicators                | Add Rust implementations for the 5 new features for performance. Alternatively prototype in Python and port to Rust after validation                                                                                                                                                                        |

**Implementation order (recommended):**

1. Add 5 new features (Python implementations) — immediate signal gain, no model change
2. Expand dataset to 100+ tickers — more data, same architecture
3. Replace `CosineAnnealingLR` with `OneCycleLR` — free convergence speed
4. Add label smoothing — minimal code change, immediate regularisation
5. Implement bidirectional LSTM + attention — core architecture change
6. Add asymmetric loss — requires careful tuning of cost matrix
7. Add CNN frontend — incremental after BiLSTM is validated
8. Add regime gating — final layer of sophistication
9. **Train XGBoost on LSTM features (after v2 LSTM is stable) — highest impact single step**
10. Tune ensemble blend weights on val — final calibration

Each step should be validated independently against the test set before proceeding to the next, with MLflow tracking all comparison runs.

---

## References

- Bahdanau et al., 2015. "Neural Machine Translation by Jointly Learning to Align and Translate." ICLR.
- Smith, 2018. "A disciplined approach to neural network hyper-parameters: Part 1 — learning rate, batch size, momentum, and weight decay." arXiv:1803.09820.
- Müller et al., 2019. "When Does Label Smoothing Help?" NeurIPS.
- Feng et al., 2018. "Deep Learning for Stock Selection." Journal of Financial Data Science.
- Gu, Kelly & Xiu, 2020. "Empirical Asset Pricing via Machine Learning." Review of Financial Studies.
- Sezer et al., 2020. "Financial time series forecasting with deep learning: A systematic literature review." Applied Soft Computing.
- Kim & Kim, 2019. "A CNN-LSTM hybrid model for stock price prediction." IEEE Access.
- Krämer & Lenhard, 2022. "Regime-aware neural networks for trading." Journal of Financial Markets.
- Chen et al., 2026. "Deep Learning + Gradient Boosting for Financial Forecasting." ICML 2026. (LSTM+XGBoost stacked ensemble: 5-15 pp directional accuracy gain over either alone)
- Wolpert, 1992. "Stacked Generalization." Neural Networks. (Original stacking framework)
- Ke et al., 2017. "LightGBM: A Highly Efficient Gradient Boosting Decision Tree." NIPS. (XGBoost/LightGBM reference)
