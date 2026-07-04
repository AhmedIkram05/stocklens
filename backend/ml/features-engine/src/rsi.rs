//! Compute Relative Strength Index (RSI) using a simple rolling average
//! (matching pandas ``rolling(window=period).mean()`` behaviour).

use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

pub fn compute(close: &[f64], period: usize) -> Py<PyArray1<f64>> {
    let n = close.len();
    let mut result = crate::alloc_nans(n);

    if n <= period {
        return make_array(result);
    }

    // Daily gains and losses
    let mut gains = vec![0.0; n];
    let mut losses = vec![0.0; n];
    for i in 1..n {
        let diff = close[i] - close[i - 1];
        if diff > 0.0 {
            gains[i] = diff;
        } else {
            losses[i] = -diff;
        }
    }

    // Sliding-window SMA of gains/losses (matching pandas rolling().mean())
    let mut sum_gain: f64 = gains[1..=period].iter().sum();
    let mut sum_loss: f64 = losses[1..=period].iter().sum();

    for i in period..n {
        if i > period {
            sum_gain += gains[i] - gains[i - period];
            sum_loss += losses[i] - losses[i - period];
        }
        let avg_gain = sum_gain / period as f64;
        let avg_loss = sum_loss / period as f64;

        if avg_loss != 0.0 {
            let rs = avg_gain / avg_loss;
            result[i] = 100.0 - (100.0 / (1.0 + rs));
        } else {
            result[i] = 100.0;
        }
    }

    make_array(result)
}

fn make_array(data: Vec<f64>) -> Py<PyArray1<f64>> {
    Python::initialize();
    Python::attach(|py| data.to_pyarray(py).into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use numpy::PyArrayMethods;
    use rand::SeedableRng;

    #[test]
    fn test_rsi_all_up() {
        let close: Vec<f64> = (0..30).map(|i| 100.0 + i as f64).collect();
        let rsi_result = compute(&close, 14);
        Python::initialize();
        Python::attach(|py| {
            let arr = rsi_result.bind(py);
            let ro = arr.readonly();
            let vals = ro.as_slice().unwrap();
            let last_val = vals.iter().filter(|x| !x.is_nan()).last().unwrap();
            assert!((last_val - 100.0).abs() < 1e-4);
        });
    }

    #[test]
    fn test_rsi_all_down() {
        let close: Vec<f64> = (0..30).map(|i| 200.0 - i as f64).collect();
        let rsi_result = compute(&close, 14);
        Python::initialize();
        Python::attach(|py| {
            let arr = rsi_result.bind(py);
            let ro = arr.readonly();
            let vals = ro.as_slice().unwrap();
            let last_val = vals.iter().filter(|x| !x.is_nan()).last().unwrap();
            assert!((last_val - 0.0).abs() < 1e-4);
        });
    }

    #[test]
    fn test_rsi_period_plus_one_gives_one_value() {
        // n = period + 1 was rejected by the old guard (n <= period + 1).
        // With 15 data points for RSI(14), exactly one RSI value should
        // be produced at index 14.
        let close: Vec<f64> = (0..15).map(|i| 100.0 + i as f64).collect();
        let rsi_result = compute(&close, 14);
        Python::initialize();
        Python::attach(|py| {
            let arr = rsi_result.bind(py);
            let ro = arr.readonly();
            let vals = ro.as_slice().unwrap();
            assert_eq!(vals.len(), 15);
            assert!(vals[14] == 100.0);
            // All other entries remain NaN
            for i in 0..14 {
                assert!(vals[i].is_nan(), "vals[{}] should be NaN, got {}", i, vals[i]);
            }
        });
    }

    #[test]
    fn test_rsi_bounds() {
        use rand::Rng;
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        let mut prices = vec![100.0];
        for _ in 1..252 {
            let ret = (rng.gen::<f64>() - 0.5) * 0.06;
            prices.push(prices.last().unwrap() * (1.0 + ret));
        }
        let rsi_result = compute(&prices, 14);
        Python::initialize();
        Python::attach(|py| {
            let arr = rsi_result.bind(py);
            let ro = arr.readonly();
            let vals = ro.as_slice().unwrap();
            let finites: Vec<f64> = vals.iter().filter(|x| !x.is_nan()).copied().collect();
            assert!(!finites.is_empty());
            for &v in &finites {
                assert!(v >= 0.0 && v <= 100.0, "RSI {} out of [0, 100]", v);
            }
        });
    }
}
