# GlobalLSTM — Architecture & Research Record

> Directional stock movement prediction (UP / FLAT / DOWN) using a multi-ticker LSTM with entity embeddings. This document describes the **current, rebuilt** architecture (branch `fix/weak-LSTM`), the validity fixes applied to the training/evaluation loop, and the honest results.

---

## 1. Model Architecture

`GlobalLSTM` (`backend/ml/model.py`) — shared weights across all tickers, per-ticker entity
embedding, single forward pass per window.

```text
Components            Dimension         Details
─────────────────────────────────────────────────────
Ticker Embedding      16                nn.Embedding(vocab_size, 16, padding_idx=UNK)
Feature Projection    33 → 112          Linear(17+16 → hidden) + ReLU
LSTM                  112 → 112         2 layers, unidirectional, batch_first
Dropout               0.45              nn.Dropout
Classifier            112 → 3           Linear → logits (no softmax)
```

- **hidden_dim 112, dropout 0.45, wd 8e-5, lr 0.0087, focal γ 1.19** are Optuna HPO best
  (phase 1, trial 15, val_dir_acc 0.5090). All overridable via env
  (`ML_HIDDEN_DIM`, `ML_DROPOUT`, `ML_WD`, `ML_LR`, `ML_FOCAL_GAMMA`, `ML_EMBED_DIM`,
  `ML_SEQ_LEN`, `ML_T_MAX`, `ML_EPOCHS`, `ML_SEEDS`).
- **Abstention/margin rule:** if `|p_up − p_down| < margin` the model predicts FLAT (no trade).
  Margin is swept on **validation** long-short Sharpe only when `ML_MARGIN_SWEEP=1` (default off —
  argmax over 17 margins on a noisy val metric was a repeatable winner's curse; a
  `MARGIN_MIN_COVERAGE=0.20` guard rejects near-empty portfolios). The selected margin is stored
  in the checkpoint and applied identically at inference.
- **5-seed probability ensemble:** with `ML_SEEDS=5`, five models (seeds 42–46) are trained and
  the champion is the **mean of softmax probabilities** across seeds. Per-seed variance is
  ±1.0pp on test directional accuracy — averaging removes the seed lottery that made single-seed
  runs look randomly strong/weak. Ensemble members are saved as `model_seed{i}.pt` next to the
  canonical `model.pt` (seed 0) and are loaded by both the serving layer and the promotion gate.

### Feature set (17 total)

| #  | Feature          | Source | Notes                                                    |
|----|------------------|--------|----------------------------------------------------------|
| 1–3 | `log_ret_1d/5d/21d` | Rust | Momentum (computed from `adjusted_close`)            |
| 4–7 | `ma_5/10/20/50`  | Rust   | **Scale-free**: stored as `log(close / ma)` — survives cross-era price-level drift |
| 8  | `rsi_14`         | Rust   | Oscillator                                               |
| 9–11 | `macd/signal/hist` | Rust | **Scale-free**: stored as `value / close`              |
| 12 | `vol_30d`        | Rust   | Rolling 30d std of log returns                           |
| 13 | `vol_rank`       | Rust   | Causal 252-day rolling rank (no look-ahead)              |
| 14 | `vol_pct`        | Python | **Causal** expanding percentile rank of vol_30d (`compute_causal_vol_pct`, `min_periods=60`) — shared helper used identically by training pipeline and the prediction service |
| 15–17 | `excess_ret_1d/5d/21d` | Python | Cross-sectional log-return excess vs SPY |

The Rust engine also computes 6 V2 indicators (Bollinger %B/width, ATR-14, OBV, Williams %R,
ROC-10) but they are **dropped** — with the old small dataset each one pushed the model toward
single-class collapse. Re-test candidate now that data is ~3× larger.

### Labels

Adaptive volatility-scaled labels: `FLAT` when `|fwd_log_ret_5d| < threshold_mult · σ_30d · √h`.
The winning recipe uses **`ML_THRESHOLD_MULT=2.0`** — a wider FLAT band (~73% of test days) that
stops the model from being forced to trade on noise. Consequence: **3-class accuracy is ~3.5%**
(large FLAT majority), and the honest headline metric is **directional accuracy** (accuracy among
non-FLAT labels, chance = 50%).

---

## 2. Data & Split Integrity

- **Database:** 7,389 tickers / 28.2M daily rows, 1962 → 2026-07-09. Bulk-loaded from the
  Kaggle `jacksoncrow/stock-market-dataset` snapshot via `scripts/seed_ohlcv_kaggle.py`
  (idempotent, `ON CONFLICT DO NOTHING`, poison-row guard) plus live yfinance data for recent dates.
- **Training universe:** `TRAINING_TICKERS=ALL` resolves to the full S&P 500 list; a **recency
  filter** (`TICKER_MIN_RECENCY_DAYS=90`) then drops Kaggle-only delisted names whose data ends
  in 2020 — dead tickers can never appear in a 2024-26 test era and only add survivorship noise.
  Current 10-year runs train on ~102 liquid tickers (~152k windows).
- **Chronological 70/15/15 split with a 10-day embargo** (`EMBARGO_DAYS = 2 × FORECAST_HORIZON`):
  training windows whose label horizon overlaps the val/test boundary are dropped.
- **NaN hygiene:** windows containing any NaN feature are filtered (previously garbage z-scored
  zeros were fed to the model); normalization means/stds fit on **train only**.
- **Vol filter (`ML_VOL_FILTER`) is optional, default OFF, and train-only** when enabled —
  filtering val/test skewed the old test set and mismatched deployment.
- `OHLCV_YEARS` (env `ML_OHLCV_YEARS`) is a global cutoff; 10-year runs are the current recipe.

---

## 3. Methodology Fixes (what was actually broken, and the fix)

| # | Flaw (pre-rebuild) | Fix |
|---|--------------------|-----|
| 1 | HPO phase 2 selected the label threshold by **test-set** accuracy | All selection on validation; test logged once, reporting-only |
| 2 | `vol_pct` was a **full-history percentile rank** (look-ahead) and inference used a short-window rank (train/serve skew) | `compute_causal_vol_pct` — expanding rank with `min_periods=60`, same helper at train and serve; inference fetch window sized by `PREDICTION_FETCH_LIMIT = max(2100, OHLCV_YEARS×260)` |
| 3 | Fake Sharpe: ±1% label-magnitude proxy, ×252 annualization on 5-day returns, no dates/costs | Deleted. `evaluate._strategy_sharpe`: per-window **actual forward log returns**, non-overlapping stride-h windows per ticker, per-date equal-weight portfolio, annualization `√(252/h)`, reported at 0bps and `COST_BPS_ROUND_TRIP=10`bps |
| 4 | No purge/embargo at split boundaries (5-day label overlap) | 10-day embargo on train before val, val before test |
| 5 | Early stopping / HPO objective on single-epoch val accuracy (±1.2pp noise) | Smoothed metric: mean of last-3 epochs' val directional accuracy; HPO objective = same smoothed value |
| 6 | FocalLoss `pt` computed from **weighted** CE → mis-calibrated focal factor | `pt` from unweighted CE; class weights applied separately (`ML_CLASS_WEIGHTS`, needed — plain CE collapses to always-FLAT) |
| 7 | Optuna MedianPruner never pruned (intermediates reported after training) | `epoch_callback` reports val metrics **inside** the epoch loop; `TrialPruned` raised mid-run. Persistent storage: `backend/ml/.optuna/lstm_hpo.sqlite` |
| 8 | HPO phase 1 saved a champion to disk, **bypassing the promotion gate** | Removed — HPO never touches the champion |
| 9 | Unpaired promotion gate (champion DA from an old period treated as a fixed binomial baseline) | **Paired McNemar gate**: the champion is re-scored on the challenger's test set (its own means/stds/vocab — ticker indices remapped via `inv_vocab → champion._vocab`; ensemble champions are re-scored as an ensemble). `decide_promotion_paired` = effect size ≥2pp **and** exact two-sided McNemar p<0.05. Unpaired binomial kept only as documented fallback |
| 10 | Test-time leakage in margin/threshold selection | Margin sweep (when enabled) selects on val only; label threshold tuned on val only |

Other: the Seed-everything contract (`set_seed`) covers torch/numpy/random per run; scheduler is
`CosineAnnealingLR(T_max=ML_T_MAX or n_epochs)`; seed-0 model is the registered artifact.

---

## 4. Honest Results (10-year window, ~102 tickers, threshold_mult=2.0)

| Metric | Rebuilt LSTM (5-seed ensemble) | Context |
| --- | --- | --- |
| Test directional accuracy | **53.17%** (n_dir=2221, SE ≈ 1.1pp) | Coverage 100%, margin 0 |
| Per-seed range | 50.5% – 55.8% (mean 52.2% ± 1.0pp) | Seed variance is real — ensemble is the point |
| HistGradientBoosting baseline (same splits) | 50.83% | `ml/baselines.py`, class_weight-balanced LR: 49.06% |
| Old champion (pre-rebuild) | 49.95% | Old "51.63%" was test-set-selected |
| Long-only Sharpe | ~2.85 @ 10bps costs | Real forward returns, stride-5, per-date EW |
| Long-short Sharpe | ≈ 0 @ 10bps costs | The LS edge does not survive transaction costs |
| 3-class accuracy | ~3.5% | By design at threshold 2.0 (~73% FLAT labels); abstention-first framing |

Promotion history: the ensemble was promoted via the (then-available) unpaired gate
(+3.2pp, binomial p<0.05). The **paired McNemar gate is verified end-to-end**: a later challenger
(52.36%) was correctly blocked — the champion re-scored on that challenger's test set reproduced
53.17% exactly (discordant pairs b=275 / c=293, p=0.476).

---

## 5. Serving Path

- `backend/src/prediction/service.py` loads `model.pt` **plus all `model_seed*.pt`** siblings;
  predictions are the mean softmax across ensemble members (single-model fallback preserved).
- The margin rule from the checkpoint is applied identically at inference
  (`edge = p_up − p_down`; ≥ margin → UP, ≤ −margin → DOWN, else FLAT).
- `vol_pct` at inference uses the **same** `compute_causal_vol_pct` helper on a fetch window of
  `PREDICTION_FETCH_LIMIT` rows, so the feature distribution matches training.
- Verified live: `GET /predict/AAPL` → UP, confidence 0.417, `ensemble_size=5`.

---

## 6. Known Limitations (documented honestly)

1. **Long-short edge ≈ 0 after costs.** The profitable regime is long-only on UP signals.
2. **Single chronological split.** Walk-forward / multi-fold evaluation is not implemented yet.
3. **Label smoothing and a binary (UP/DOWN) collapse** ablation were not run.
4. **V2 Rust features** (BB %B/width, ATR, OBV, Williams %R, ROC) remain dropped; re-test with the larger dataset is pending.
5. **Prod env wiring:** the ECS task definition does not yet set `TRAINING_TICKERS`/`OHLCV_YEARS`, so a prod weekly retrain would use the dev subset.
6. **MPS checkpoint-load bug:** loading saved checkpoints onto Apple MPS can raise
   `Placeholder storage has not been allocated on MPS device!` in `F.embedding`. The promotion
   gate therefore re-scores champions on **CPU** (`gate_device`); live serving runs on CPU too.
7. `torch.compile` crashes on repo paths containing spaces (inductor/clang) — CPU compile is disabled in practice for this checkout location.

---

## 7. Remaining Roadmap (ranked)

1. **Walk-forward evaluation** — rolling-origin folds instead of a single split; report mean ± CI across folds.
2. **Binary collapse ablation** (UP vs DOWN only, abstain via margin) vs 3-class + threshold.
3. **Label smoothing ablation** (ε=0.05/0.1) for calibration.
4. **Re-test V2 Rust features** on the 3×-larger dataset.
5. **Prod env wiring** for `TRAINING_TICKERS` / `ML_OHLCV_YEARS` in the ECS task definition.
6. Optional: HPO phase 2 re-run on the new recipe; per-ticker horizon ensembling.

---

## References

- Optuna: Akiba et al., 2019 (TPE + median pruning) — https://optuna.org
- McNemar test: McNemar, 1947; exact two-sided variant via `math.comb` in `ml/promotion_stats.py`.
- Focal loss: Lin et al., 2017 — `pt` must come from the *unweighted* softmax probability.
- Sharpe with stride-h non-overlapping holds: annualization `√(252/h)` follows from i.i.d. h-day
  variance scaling; see Lo (2002), "The Statistics of Sharpe Ratios".
- Kaggle dataset: `jacksoncrow/stock-market-dataset` (US equities + ETFs, 1962–2020 snapshot).
