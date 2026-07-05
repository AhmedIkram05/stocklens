//! Compute Williams %R.
//!
//! %R = (highest_high - close) / (highest_high - lowest_low) * -100
//!
//! Where highest_high = max(high[i-period+1..=i]),
//!       lowest_low   = min(low[i-period+1..=i])
//!
//! Values lie in [-100, 0].

use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

pub fn compute(high: &[f64], low: &[f64], close: &[f64], period: usize) -> Py<PyArray1<f64>> {
    let n = high.len().min(low.len()).min(close.len());
    let mut result = crate::alloc_nans(n);

    if n < period {
        return make_array(result);
    }

    for i in (period - 1)..n {
        let start = i + 1 - period;
        let highest = high[start..=i]
            .iter()
            .copied()
            .fold(f64::NEG_INFINITY, f64::max);
        let lowest = low[start..=i]
            .iter()
            .copied()
            .fold(f64::INFINITY, f64::min);

        let range = highest - lowest;
        if range != 0.0 {
            result[i] = (highest - close[i]) / range * -100.0;
        } else {
            result[i] = 0.0; // flat range → %R = 0
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

    #[test]
    fn test_williams_r_basic() {
        let high = vec![110.0, 112.0, 115.0, 113.0, 116.0, 118.0, 120.0];
        let low  = vec![105.0, 108.0, 109.0, 110.0, 112.0, 114.0, 115.0];
        let close = vec![108.0, 110.0, 112.0, 111.0, 115.0, 117.0, 118.0];

        Python::initialize();
        Python::attach(|py| {
            let result = compute(&high, &low, &close, 3);
            let arr = result.bind(py);
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            assert_eq!(vals.len(), 7);
            assert!(vals[0].is_nan());
            assert!(vals[1].is_nan());
            assert!(!vals[2].is_nan());
            assert!(vals[2] >= -100.0 && vals[2] <= 0.0);
            assert!(vals[6] >= -100.0 && vals[6] <= 0.0);
        });
    }

    #[test]
    fn test_williams_r_bounds() {
        // All prices rising monotonically → overbought territory
        let high: Vec<f64> = (0..30).map(|i| 110.0 + i as f64).collect();
        let low: Vec<f64> = (0..30).map(|i| 100.0 + i as f64).collect();
        let close: Vec<f64> = (0..30).map(|i| 105.0 + i as f64).collect();

        Python::initialize();
        Python::attach(|py| {
            let result = compute(&high, &low, &close, 5);
            let arr = result.bind(py);
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            for &v in vals.iter().filter(|x| !x.is_nan()) {
                assert!(v >= -100.0 && v <= 0.0, "%R {} out of [-100, 0]", v);
            }
        });
    }
}
