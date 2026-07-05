//! StockLens Feature Engine — Rust/PyO3 technical indicators.

mod atr;
mod bollinger;
mod compute_all;
mod log_returns;
mod macd;
mod moving_averages;
mod obv;
mod roc;
mod rolling_volatility;
mod rsi;
mod volatility_rank;
mod williams_r;

use numpy::{PyArray1, PyArrayMethods};
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Helper: allocate a new f64 vec of length n, filled with f64::NAN.
fn alloc_nans(n: usize) -> Vec<f64> {
    vec![f64::NAN; n]
}

/// Helper: compute EMA with smoothing factor `alpha = 2 / (span + 1)`.
/// Skips leading NaNs — starts seeding the SMA once `span` consecutive
/// non-NaN values are seen. Required for MACD signal line (macd_line has
/// leading NaNs from the slow EMA warmup).
// ponytail: simple leading-NaN skip; a streaming incremental EMA would avoid
// the O(span) seed scan but adds complexity for no measurable gain.
fn ema(values: &[f64], span: usize) -> Vec<f64> {
    let n = values.len();
    if n == 0 || span == 0 {
        return vec![];
    }
    let alpha = 2.0 / (span as f64 + 1.0);
    let mut result = alloc_nans(n);

    // Find the first run of `span` consecutive non-NaN values.
    let mut seed_end: Option<usize> = None;
    let mut run = 0;
    for i in 0..n {
        if values[i].is_nan() {
            run = 0;
        } else {
            run += 1;
            if run == span {
                seed_end = Some(i);
                break;
            }
        }
    }

    if let Some(end) = seed_end {
        let start = end + 1 - span;
        let sum: f64 = values[start..=end].iter().sum();
        result[end] = sum / span as f64;
        let mut last_valid = end;
        for i in (end + 1)..n {
            if values[i].is_nan() {
                // Hold previous EMA value forward (common convention).
                result[i] = result[last_valid];
            } else {
                result[i] = (values[i] - result[last_valid]) * alpha + result[last_valid];
                last_valid = i;
            }
        }
    }
    result
}

/// Helper: extract f64 slice from a Bound<'_, PyArray1<f64>>.
fn get_slice(arr: &Bound<'_, PyArray1<f64>>) -> Vec<f64> {
    arr.readonly().as_slice().unwrap().to_vec()
}

/// Register the Python module.
#[pymodule]
fn features_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_log_returns, m)?)?;
    m.add_function(wrap_pyfunction!(compute_moving_averages, m)?)?;
    m.add_function(wrap_pyfunction!(compute_rsi, m)?)?;
    m.add_function(wrap_pyfunction!(compute_macd, m)?)?;
    m.add_function(wrap_pyfunction!(compute_rolling_volatility, m)?)?;
    m.add_function(wrap_pyfunction!(compute_volatility_rank, m)?)?;
    m.add_function(wrap_pyfunction!(compute_bollinger, m)?)?;
    m.add_function(wrap_pyfunction!(compute_atr, m)?)?;
    m.add_function(wrap_pyfunction!(compute_obv, m)?)?;
    m.add_function(wrap_pyfunction!(compute_williams_r, m)?)?;
    m.add_function(wrap_pyfunction!(compute_roc, m)?)?;
    m.add_function(wrap_pyfunction!(compute_all_features, m)?)?;
    Ok(())
}

// --- Exported function wrappers ---

#[pyfunction]
fn compute_log_returns(
    py: Python<'_>,
    close: Bound<'_, PyArray1<f64>>,
    periods: Vec<i64>,
) -> PyResult<Py<PyDict>> {
    let close_slice = get_slice(&close);
    Ok(log_returns::compute(&close_slice, &periods, py))
}

#[pyfunction]
fn compute_moving_averages(
    py: Python<'_>,
    close: Bound<'_, PyArray1<f64>>,
    windows: Vec<i64>,
) -> PyResult<Py<PyDict>> {
    let close_slice = get_slice(&close);
    Ok(moving_averages::compute(&close_slice, &windows, py))
}

#[pyfunction]
fn compute_rsi(close: Bound<'_, PyArray1<f64>>, period: i64) -> PyResult<Py<PyArray1<f64>>> {
    let close_slice = get_slice(&close);
    Ok(rsi::compute(&close_slice, period as usize))
}

#[pyfunction]
fn compute_macd(
    py: Python<'_>,
    close: Bound<'_, PyArray1<f64>>,
    fast: i64,
    slow: i64,
    signal: i64,
) -> PyResult<Py<PyDict>> {
    let close_slice = get_slice(&close);
    Ok(macd::compute(&close_slice, fast as usize, slow as usize, signal as usize, py))
}

#[pyfunction]
fn compute_rolling_volatility(close: Bound<'_, PyArray1<f64>>, period: i64) -> PyResult<Py<PyArray1<f64>>> {
    let close_slice = get_slice(&close);
    Ok(rolling_volatility::compute(&close_slice, period as usize))
}

#[pyfunction]
fn compute_volatility_rank(close: Bound<'_, PyArray1<f64>>, period: i64) -> PyResult<Py<PyArray1<f64>>> {
    let close_slice = get_slice(&close);
    Ok(volatility_rank::compute(&close_slice, period as usize))
}

#[pyfunction]
fn compute_bollinger(
    py: Python<'_>,
    close: Bound<'_, PyArray1<f64>>,
    period: i64,
    num_std: f64,
) -> PyResult<Py<PyDict>> {
    let close_slice = get_slice(&close);
    Ok(bollinger::compute(&close_slice, period as usize, num_std, py))
}

#[pyfunction]
fn compute_atr(
    high: Bound<'_, PyArray1<f64>>,
    low: Bound<'_, PyArray1<f64>>,
    close: Bound<'_, PyArray1<f64>>,
    period: i64,
) -> PyResult<Py<PyArray1<f64>>> {
    let high_slice = get_slice(&high);
    let low_slice = get_slice(&low);
    let close_slice = get_slice(&close);
    Ok(atr::compute(&high_slice, &low_slice, &close_slice, period as usize))
}

#[pyfunction]
fn compute_obv(
    close: Bound<'_, PyArray1<f64>>,
    volume: Bound<'_, PyArray1<f64>>,
) -> PyResult<Py<PyArray1<f64>>> {
    let close_slice = get_slice(&close);
    let volume_slice = get_slice(&volume);
    Ok(obv::compute(&close_slice, &volume_slice))
}

#[pyfunction]
fn compute_williams_r(
    high: Bound<'_, PyArray1<f64>>,
    low: Bound<'_, PyArray1<f64>>,
    close: Bound<'_, PyArray1<f64>>,
    period: i64,
) -> PyResult<Py<PyArray1<f64>>> {
    let high_slice = get_slice(&high);
    let low_slice = get_slice(&low);
    let close_slice = get_slice(&close);
    Ok(williams_r::compute(&high_slice, &low_slice, &close_slice, period as usize))
}

#[pyfunction]
fn compute_roc(
    close: Bound<'_, PyArray1<f64>>,
    period: i64,
) -> PyResult<Py<PyArray1<f64>>> {
    let close_slice = get_slice(&close);
    Ok(roc::compute(&close_slice, period as usize))
}

#[pyfunction]
fn compute_all_features(
    py: Python<'_>,
    close: Bound<'_, PyArray1<f64>>,
    high: Bound<'_, PyArray1<f64>>,
    low: Bound<'_, PyArray1<f64>>,
    volume: Bound<'_, PyArray1<f64>>,
) -> PyResult<Py<PyDict>> {
    let close_slice = get_slice(&close);
    let high_slice = get_slice(&high);
    let low_slice = get_slice(&low);
    let volume_slice = get_slice(&volume);
    Ok(compute_all::compute(&close_slice, &high_slice, &low_slice, &volume_slice, py))
}
