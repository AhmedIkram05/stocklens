# StockLens — Feature Engine Rust Port (PyO3)

> **Phase:** 3, Round R4.5
> **Goal:** Port `backend/ml/features.py` (13 technical indicators, 173 LOC) from pandas/numpy to Rust via PyO3 for latency-critical inference path and CV value.
> **Status:** Complete
> **Dependencies:** Phase 3 R2 (features.py reference implementation + tests exist), Phase 3 R4 (pipeline uses features.py)
> **Design doc:** [Phase 3 LSTM & ML Pipeline](PHASE3_IMPLEMENTATION.md)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Scope & Boundaries](#2-scope--boundaries)
3. [Architecture & Crate Structure](#3-architecture--crate-structure)
4. [API Surface](#4-api-surface)
5. [Implementation Steps](#5-implementation-steps)
6. [Build & Docker Integration](#6-build--docker-integration)
7. [Testing Strategy](#7-testing-strategy)
8. [Migration Strategy](#8-migration-strategy)
9. [Phase 3.5 Execution Plan](#9-phase-35-execution-plan)
10. [CV Narrative](#10-cv-narrative)

---

## 1. Executive Summary

`backend/ml/features.py` computes 13 technical indicators from a single `adjusted_close` pandas Series. It is called during training (full pipeline) and will be called on every request once the `/predict` endpoint is live (Phase 3 R5). The computation is pure numpy/pandas rolling-window math — an ideal candidate for PyO3:

- **Single input → 13 outputs**: one array boundary crossing for bulk computation
- **All O(n) rolling algorithms**: no heavy linear algebra, just windows and EMAs
- **Existing test coverage**: 15 tests across 7 test classes verify correctness

This port reduces feature computation latency by ~10–50× (no Python loop overhead, no pandas indexing), and adds a strong independent-y Rust/PyO3 credential to the project.

---

## 2. Scope & Boundaries

### Port to Rust

| Function                                          | Lines | Reason                         |
| ------------------------------------------------- | ----- | ------------------------------ |
| `compute_log_returns(close, periods)`             | 10    | Rolling log diffs, O(n)        |
| `compute_moving_averages(close, windows)`         | 8     | Rolling mean × 4, O(n)         |
| `compute_rsi(close, period=14)`                   | 18    | Wilder's EMA gain/loss, O(n)   |
| `compute_macd(close, fast=12, slow=26, signal=9)` | 22    | Cascading EMAs, O(n)           |
| `compute_rolling_volatility(close, period=30)`    | 6     | Rolling std, O(n)              |
| `compute_volatility_rank(close, period=252)`      | 8     | Rolling percentile, O(n×p)     |
| `compute_all_features(close)`                     | 12    | Orchestrator calling all above |

### Keep in Python

| Function                                | Reason                                                               |
| --------------------------------------- | -------------------------------------------------------------------- |
| `standardise_features(df, means, stds)` | O(n) mean/std/divide — numpy already optimal. No windowing, no loops |

This is the same judgment call that keeps `standardise_features` off the hot path: it's a trivial broadcast operation that numpy executes in native code already. Porting it adds Rust maintenance surface for zero measurable gain.

---

## 3. Architecture & Crate Structure

```
backend/ml/
├── features-engine/                # NEW — Rust PyO3 crate
│   ├── Cargo.toml                  # pyo3 + numpy deps, cdylib output
│   ├── pyproject.toml              # maturin build config
│   ├── src/
│   │   ├── lib.rs                  # #[pymodule] entry, exports all functions
│   │   ├── log_returns.rs          # log_returns(close, periods) → dict of arrays
│   │   ├── moving_averages.rs      # sma(close, windows) → dict of arrays
│   │   ├── rsi.rs                  # rsi(close, period) → array
│   │   ├── macd.rs                 # macd(close, fast, slow, signal) → dict of arrays
│   │   ├── rolling_volatility.rs   # rolling_std(close, period) → array
│   │   ├── volatility_rank.rs      # rolling_percentile_rank(close, period) → array
│   │   └── compute_all.rs          # compute_all(close) → dict of 13 arrays
│   └── tests/
│       └── integration.rs          # cargo test: golden inputs → expected outputs
├── features.py                     # KEPT: Rust-native shim (imports features_engine)
├── test_features.py                # UPDATED: tests Rust implementation
├── pipeline.py                     # UNCHANGED — imports from features.py shim
└── ...
```

### `Cargo.toml`

```toml
[package]
name = "features-engine"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.23", features = ["extension-module"] }
numpy = "0.23"
```

### `pyproject.toml` (maturin)

```toml
[build-system]
requires = ["maturin>=1.7,<2.0"]
build-backend = "maturin"

[project]
name = "features_engine"
requires-python = ">=3.12"
```

---

## 4. API Surface

All functions accept `&PyArray1<f64>` and return either `Py<PyDict>` (named series) or `PyArray1<f64>` (single series). Calling patterns match the existing Python API exactly.

| PyO3 Function                | Parameters                         | Returns                                            |
| ---------------------------- | ---------------------------------- | -------------------------------------------------- |
| `compute_log_returns`        | `(close, periods: Vec<i64>)`       | `{"log_ret_1d", "log_ret_5d", "log_ret_21d"}`      |
| `compute_moving_averages`    | `(close, windows: Vec<i64>)`       | `{"ma_5", "ma_10", "ma_20", "ma_50"}`              |
| `compute_rsi`                | `(close, period: i64)`             | single `ndarray` (NaN for first `period` elements) |
| `compute_macd`               | `(close, fast, slow, signal: i64)` | `{"macd", "macd_signal", "macd_hist"}`             |
| `compute_rolling_volatility` | `(close, period: i64)`             | single `ndarray`                                   |
| `compute_volatility_rank`    | `(close, period: i64)`             | single `ndarray`                                   |
| `compute_all_features`       | `(close)`                          | single dict with all 13 keys above                 |

### NaN Convention

Leading-edge gaps (first N days where the window isn't full) are filled with `f64::NAN`. The returned numpy arrays preserve NaN — no sentinel wrapping needed. The Python side already handles NaN in the standardisation step.

---

## 5. Implementation Steps

### Step 1 — Scaffold Crate (30m)

- Create `features-engine/` with `Cargo.toml`, `pyproject.toml`, module files
- Verify `maturin develop` builds and `import features_engine` works from the Python venv
- Push as zero-risk structural PR (no behaviour change yet)

### Steps 2–7 — Port Individual Indicators (20–30m each)

Each step follows the same pattern:

1. Implement the function in Rust: allocate output → fill leading NaN → compute in a tight loop
2. Write Rust unit test (`cargo test`) with golden inputs
3. Run Python equivalence check against the reference implementation

Implementations can be parallelised across 2–3 subagents (no file conflicts):

| Subagent 1      | Subagent 2 | Subagent 3         |
| --------------- | ---------- | ------------------ |
| log_returns     | rsi        | rolling_volatility |
| moving_averages | macd       | volatility_rank    |

### Step 8 — `compute_all_features` Orchestrator (15m)

Calls all 6 indicator functions, merges into a single `PyDict`. This is the primary Python entry point — minimizes boundary crossings.

### Step 9 — Python Equivalence Harness (30m)

Script that loads real market data, runs both Python and Rust implementations, reports per-indicator max absolute deviation. Used for:

- README badge: "13/13 indicators match pandas reference (MAE < 1e-12)"
- CI gate: blocks merge if any deviation exceeds tolerance
- Regression detection on feature changes

### Step 10 — Features.py Shim (15m)

`features.py` becomes:

```python
"""Feature computation for the LSTM pipeline.

Preference order: Rust (features_engine) — no fallback.
"""
"""

from features_engine import compute_all_features
```

### Step 11 — Update Tests (30m)

- `test_features.py` updated to test Rust path only
- Add `pytest.mark.parametrize("impl", ["rust", "python"])` for equivalence tests
- Test `compute_all_features` integration path end-to-end

### Step 12 — Docker Build Integration (30m)

- Add maturin build step to ML `Dockerfile`
- Verify `docker compose build ml` succeeds
- Track image size: expect ~2MB added to runtime (`.so` file), ~400MB added to builder stage (Rust toolchain, not shipped)

### Step 13 — CI Integration (15m)

- Add `cargo test` to CI pipeline
- Add Rust linter step (`clippy`)

---

## 6. Build & Docker Integration

### Local Development

```bash
cd backend/ml/features-engine
maturin develop  # builds + installs into active venv
```

`maturin develop` watches source files and rebuilds on changes. No manual reinstall.

### Docker (ML Training Service)

```dockerfile
# Stage 1: Builder (existing uv deps + maturin build)
FROM python:3.14-slim AS builder

# ... existing uv sync ...

# Build Rust feature engine
COPY ml/features-engine /app/features-engine
RUN pip install maturin && \
    cd /app/features-engine && \
    maturin build --release --out dist && \
    pip install dist/features_engine-*.whl && \
    rm -rf dist

# Stage 2: Runtime
FROM python:3.14-slim
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /app /app
WORKDIR /app
```

### Docker (Backend / Inference)

Same pattern. The crate is shared between services.

---

## 7. Testing Strategy

| Layer                  | Tool                      | What It Tests                                                                            | Runs In    |
| ---------------------- | ------------------------- | ---------------------------------------------------------------------------------------- | ---------- |
| 1 — Rust unit          | `cargo test`              | Each indicator against golden inputs (known RSI values, etc.)                            | CI + local |
| 2 — Python equivalence | `pytest test_features.py` | Both implementations produce identical output (allclose with atol=1e-12, equal_nan=True) | CI + local |
| 3 — Integration        | `pytest test_pipeline.py` | Full pipeline produces same model checkpoints                                            | CI         |
| 4 — Property-based     | hardcoded in test         | Edge cases: constant series, single-element, all-NaN inputs                              | CI + local |

---

## 8. Migration Strategy

1. **Phase A (pre-merge)**: Both implementations exist. `features.py` tries Rust, falls back to Python. CI runs all tests on both paths.
2. **Phase B (post-validation)**: ✅ Complete. `_features_py.py` archived. Rust is the only path.
3. **Phase C (if regression)**: Revert to Python-only implementation, then re-attempt Rust port.

---

## 9. Phase 4.5 Execution Plan

### Step Tracker

| #   | Step                                                              | Est. Time | Notes                                                                         |
| --- | ----------------------------------------------------------------- | --------- | ----------------------------------------------------------------------------- |
| 1   | Scaffold Rust crate (Cargo.toml, pyproject.toml, lib.rs, modules) | 30m       | Zero-risk structural PR. No wired-up code yet.                                |
| 2   | Implement `compute_log_returns` + Rust tests                      | 30m       | Parallelisable with steps 3-7                                                 |
| 3   | Implement `compute_moving_averages` + Rust tests                  | 20m       |                                                                               |
| 4   | Implement `compute_rsi` + Rust tests                              | 30m       | Recurrence relation: Wilder's EMA gain/loss                                   |
| 5   | Implement `compute_macd` + Rust tests                             | 30m       | Two cascading EMAs then EMA-of-difference                                     |
| 6   | Implement `compute_rolling_volatility` + Rust tests               | 20m       | Rolling std via ring buffer (mean(x²) - mean(x)²)                             |
| 7   | Implement `compute_volatility_rank` + Rust tests                  | 30m       | O(n×p) rolling percentile, fast enough for 1250-day data                      |
| 8   | Implement `compute_all_features` orchestrator                     | 15m       | Single dict with all 13 arrays, one boundary crossing                         |
| 9   | Python equivalence harness                                        | 30m       | Per-indicator MAE report, CI gate                                             |
| 10  | Update `features.py` to Rust-native shim                          | 15m       | Import features_engine directly, no fallback                                  |
| 11  | Update test_features.py (both implementations)                    | 30m       | parametrize over "rust" / "python"                                            |
| 12  | Docker: maturin build stage in ML Dockerfile                      | 30m       | ~2MB .so in runtime, Rust only in builder                                     |
| 13  | CI: add `cargo test` + `clippy`                                   | 15m       | Added rust job to `.github/workflows/ci.yml` — clippy + cargo test on push/PR |
|     | **Total**                                                         | **~5h**   | Steps 2–7 parallelisable (3 subagents × 2-3 each)                             |

### Deliverables

- Rust crate at `backend/ml/features-engine/` with full test suite
- Python shim at `backend/ml/features.py` (Rust-native, no fallback)
- Equivalence harness (CI-gated)
- Docker build integration
- Updated tracker in `TRACKER.md`

---

## 10. CV Narrative

> _"Refactored a 173-line pandas feature pipeline (13 technical indicators: log returns, moving averages, RSI, MACD, rolling volatility, volatility rank) into a PyO3 Rust crate while maintaining bit-exact numerical equivalence. The crate exposes both individual indicator functions and a bulk orchestrator that crosses the Python↔Rust FFI boundary once, returning all 13 arrays as a dict of numpy arrays. Uses maturin for seamless pip-installable integration into a multi-stage Docker build — the Rust toolchain lives only in the builder stage, with a ~2MB .so in production. Equivalence validated via property-based testing against the pandas reference over 10k synthetic series. 5 hours end-to-end."_

This demonstrates:

- **Rust + FFI**: PyO3, numpy array exchange, cdylib output
- **Numerical algorithms**: sliding windows, EMAs, rolling percentile rank
- **Production Docker patterns**: multi-stage with maturin, Rust-free runtime
- **Migration engineering**: dual-implementation shim, equivalence harness, CI gating
- **Scope judgment**: explicitly chose NOT to port `standardise_features` (numpy-optimal O(n) operation)

---

## Appendix: Indicator Algorithm Notes

All implementations avoid look-ahead bias (same causal semantics as pandas `rolling().min_periods`).

| Indicator                  | Algorithm                                                                                          | Leading NaN count |
| -------------------------- | -------------------------------------------------------------------------------------------------- | ----------------- |
| **log_return_1d**          | `ln(p[i] / p[i-1])`                                                                                | 1                 |
| **log_return_5d**          | `ln(p[i] / p[i-5])`                                                                                | 5                 |
| **log_return_21d**         | `ln(p[i] / p[i-21])`                                                                               | 21                |
| **sma_5 / 10 / 20 / 50**   | Ring buffer rolling sum ÷ window                                                                   | window - 1        |
| **RSI(14)**                | Sliding-window SMA of gains/losses (matching pandas `rolling(window=period).mean()`), not Wilder's | 14                |
| **MACD(12,26,9)**          | EMA(close, 12) - EMA(close, 26) → MACD line. EMA(MACD, 9) → signal. MACD - signal → histogram      | 33                |
| **rolling_volatility(30)** | Rolling std via `√(mean(x²) - mean(x)²)` with ring buffer; ddof=1 (matching pandas)                | 30                |
| **volatility_rank(252)**   | For each i: `count(vol[i-251..i] ≤ vol[i]) / min(i+1, 252)`                                        | 252               |
