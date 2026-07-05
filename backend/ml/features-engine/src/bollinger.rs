//! Compute Bollinger Bands: %B and Band Width.
//!
//! %B = (close - lower) / (upper - lower)
//! Band Width = (upper - lower) / middle

use numpy::ToPyArray;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub fn compute(close: &[f64], period: usize, num_std: f64, py: Python<'_>) -> Py<PyDict> {
    let dict = PyDict::new(py);
    let n = close.len();

    let mut middle = crate::alloc_nans(n);
    let mut bb_pctb = crate::alloc_nans(n);
    let mut bb_width = crate::alloc_nans(n);

    if n >= period {
        // SMA for the middle line
        let mut sum: f64 = close[..period].iter().sum();
        middle[period - 1] = sum / period as f64;

        for i in period..n {
            sum += close[i] - close[i - period];
            middle[i] = sum / period as f64;
        }

        // Rolling std deviation and derived values
        for i in (period - 1)..n {
            let start = i + 1 - period;
            let mean = middle[i];
            let var: f64 = close[start..=i].iter().map(|&x| (x - mean).powi(2)).sum::<f64>() / period as f64;
            let std = var.sqrt();

            let upper = mean + num_std * std;
            let lower = mean - num_std * std;

            let range = upper - lower;
            if range != 0.0 {
                bb_pctb[i] = (close[i] - lower) / range;
            }
            if mean != 0.0 {
                bb_width[i] = range / mean;
            }
        }
    }

    dict.set_item("bb_pctb", bb_pctb.to_pyarray(py)).unwrap();
    dict.set_item("bb_width", bb_width.to_pyarray(py)).unwrap();

    dict.into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use numpy::PyArrayMethods;

    #[test]
    fn test_bollinger_basic() {
        let close: Vec<f64> = (0..30).map(|i| 100.0 + i as f64).collect();
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, 5, 2.0, py);
            let dict = result.bind(py);

            let pctb = dict.get_item("bb_pctb").unwrap().unwrap();
            let arr = pctb.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            assert_eq!(vals.len(), 30);
            assert!(vals[0].is_nan());
            assert!(vals[3].is_nan());
            assert!(!vals[4].is_nan());
            // With linearly increasing prices, %B should be around 0.5
            assert!((vals[29] - 0.5).abs() < 0.1);

            let width = dict.get_item("bb_width").unwrap().unwrap();
            let arr_w = width.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let wvals = arr_w.readonly().as_slice().unwrap().to_vec();
            assert_eq!(wvals.len(), 30);
            assert!(wvals[0].is_nan());
            assert!(wvals[29] > 0.0);
        });
    }

    #[test]
    fn test_bollinger_flat() {
        let close = vec![100.0; 20];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, 5, 2.0, py);
            let dict = result.bind(py);

            let pctb = dict.get_item("bb_pctb").unwrap().unwrap();
            let arr = pctb.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            // Flat prices → std = 0 → range = 0, so %B stays at 0
            assert!(vals[4].is_nan() || vals[4] == 0.0);
        });
    }
}
