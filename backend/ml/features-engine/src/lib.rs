//! StockLens Feature Engine — Rust/PyO3 technical indicators.

mod compute_all;
mod log_returns;
mod macd;
mod moving_averages;
mod rolling_volatility;
mod rsi;
mod volatility_rank;

use numpy::{PyArray1, PyArrayMethods};
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Helper: allocate a new f64 vec of length n, filled with f64::NAN.
fn alloc_nans(n: usize) -> Vec<f64> {
    vec![f64::NAN; n]
}

/// Helper: compute EMA with smoothing factor `alpha = 2 / (span + 1)`.
fn ema(values: &[f64], span: usize) -> Vec<f64> {
    let n = values.len();
    if n == 0 {
        return vec![];
    }
    let alpha = 2.0 / (span as f64 + 1.0);
    let mut result = alloc_nans(n);
    if n >= span {
        let sum: f64 = values[..span].iter().sum();
        result[span - 1] = sum / span as f64;
        for i in span..n {
            result[i] = (values[i] - result[i - 1]) * alpha + result[i - 1];
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
fn compute_all_features(py: Python<'_>, close: Bound<'_, PyArray1<f64>>) -> PyResult<Py<PyDict>> {
    let close_slice = get_slice(&close);
    Ok(compute_all::compute(&close_slice, py))
}
