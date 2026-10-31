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

    // Daily gains and losses. A non-finite close yields an undefined diff, so
    // mark BOTH arrays NaN for that step (never a substituted 0) — the window
    // then emits NaN rather than a plausible-looking RSI on bad input.
    let mut gains = vec![0.0; n];
    let mut losses = vec![0.0; n];
    for i in 1..n {
        let diff = close[i] - close[i - 1];
        if diff.is_nan() {
            gains[i] = f64::NAN;
            losses[i] = f64::NAN;
        } else if diff > 0.0 {
            gains[i] = diff;
        } else {
            losses[i] = -diff;
        }
    }

    // Sliding-window SMA of gains/losses (matching pandas rolling().mean()).
    // The NaN counts let the running sums recover once a bad value leaves the
    // window: a NaN can never be subtracted back out.
    let mut sum_gain: f64 = 0.0;
    let mut sum_loss: f64 = 0.0;
    let mut nan_gain = 0usize;
    let mut nan_loss = 0usize;
    for i in 1..=period {
        if gains[i].is_nan() {
            nan_gain += 1;
        } else {
            sum_gain += gains[i];
        }
        if losses[i].is_nan() {
            nan_loss += 1;
        } else {
            sum_loss += losses[i];
        }
    }

    for i in period..n {
        if i > period {
            let out_g = gains[i - period];
            if out_g.is_nan() {
                nan_gain -= 1;
            } else {
                sum_gain -= out_g;
            }
            let in_g = gains[i];
            if in_g.is_nan() {
                nan_gain += 1;
            } else {
                sum_gain += in_g;
            }

            let out_l = losses[i - period];
            if out_l.is_nan() {
                nan_loss -= 1;
            } else {
                sum_loss -= out_l;
            }
            let in_l = losses[i];
            if in_l.is_nan() {
                nan_loss += 1;
            } else {
                sum_loss += in_l;
            }
        }

        if nan_gain > 0 || nan_loss > 0 {
            continue;
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
        use rand::RngExt;
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        let mut prices = vec![100.0];
        for _ in 1..252 {
            let ret = (rng.random::<f64>() - 0.5) * 0.06;
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

    #[test]
    fn test_rsi_recovers_after_nan() {
        // A single NaN diff must not poison the rolling sums forever: outputs
        // whose window holds the bad value are NaN, then the series recovers.
        let mut close: Vec<f64> = (0..30).map(|i| 100.0 + i as f64).collect();
        close[10] = f64::NAN;
        let rsi_result = compute(&close, 5);
        Python::initialize();
        Python::attach(|py| {
            let arr = rsi_result.bind(py);
            let ro = arr.readonly();
            let vals = ro.as_slice().unwrap();
            // NaN diffs at 10 and 11 → outputs 10..=15 (5-wide windows) are NaN.
            assert!(vals[10].is_nan());
            assert!(vals[15].is_nan());
            // The NaN leaves the window after 15; RSI recovers, not permanent NaN.
            assert!(vals[16].is_finite());
            assert!(vals[29].is_finite());
        });
    }
}
