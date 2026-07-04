//! Compute rolling standard deviation of daily log returns.

#![allow(clippy::needless_range_loop)]
use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

/// Pure function: returns Vec<f64> with leading NaN padding.
pub fn compute_raw(close: &[f64], period: usize) -> Vec<f64> {
    let n = close.len();
    let mut result = crate::alloc_nans(n);

    if n < 2 {
        return result;
    }

    let mut log_rets = vec![0.0; n];
    for i in 1..n {
        if close[i - 1] > 0.0 {
            log_rets[i] = (close[i] / close[i - 1]).ln();
        }
    }

    if n < period + 1 {
        return result;
    }

    // Sample standard deviation (ddof=1, matching pandas rolling().std())
    let n_float = period as f64;
    let ddof = period as f64 - 1.0;

    let mut sum = 0.0;
    let mut sum_sq = 0.0;
    for i in 1..=period {
        sum += log_rets[i];
        sum_sq += log_rets[i] * log_rets[i];
    }

    let mean = sum / n_float;
    let variance = ((sum_sq / n_float) - (mean * mean)) * n_float / ddof;
    result[period] = if variance > 0.0 { variance.sqrt() } else { 0.0 };

    for i in (period + 1)..n {
        sum += log_rets[i] - log_rets[i - period];
        sum_sq += log_rets[i] * log_rets[i] - log_rets[i - period] * log_rets[i - period];

        let mean = sum / n_float;
        let variance = ((sum_sq / n_float) - (mean * mean)) * n_float / ddof;
        result[i] = if variance > 0.0 { variance.sqrt() } else { 0.0 };
    }

    result
}

/// PyO3 wrapper: returns Py<PyArray1<f64>>.
pub fn compute(close: &[f64], period: usize) -> Py<PyArray1<f64>> {
    let data = compute_raw(close, period);
    Python::initialize();
    Python::attach(|py| data.to_pyarray(py).into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;

    #[test]
    fn test_volatility_constant() {
        let close = vec![100.0; 50];
        let raw = compute_raw(&close, 10);
        let last_val = raw.iter().filter(|x| !x.is_nan()).last().unwrap();
        assert!((*last_val).abs() < 1e-10);
    }

    #[test]
    fn test_volatility_shape() {
        use rand::Rng;
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        let mut prices = vec![100.0];
        for _ in 1..252 {
            let ret = (rng.gen::<f64>() - 0.5) * 0.06;
            prices.push(prices.last().unwrap() * (1.0 + ret));
        }
        let raw = compute_raw(&prices, 30);
        assert_eq!(raw.len(), 252);
        let nan_count = raw.iter().filter(|x| x.is_nan()).count();
        assert_eq!(nan_count, 30);
    }
}
