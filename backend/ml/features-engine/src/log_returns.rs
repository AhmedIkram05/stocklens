//! Compute multi-period log returns `ln(p[i] / p[i - period])`.

use numpy::ToPyArray;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub fn compute(close: &[f64], periods: &[i64], py: Python<'_>) -> Py<PyDict> {
    let dict = PyDict::new(py);
    let n = close.len();

    for &p in periods {
        let period = p as usize;
        let mut result = crate::alloc_nans(n);
        for i in period..n {
            if close[i - period] > 0.0 && close[i] > 0.0 {
                result[i] = (close[i] / close[i - period]).ln();
            }
        }
        dict.set_item(format!("log_ret_{p}d"), result.to_pyarray(py)).unwrap();
    }

    dict.into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use numpy::PyArrayMethods;


    #[test]
    fn test_log_returns_positive_trend() {
        let close: Vec<f64> = (0..10).map(|i| 100.0 + i as f64).collect();
        let periods = vec![1i64, 5i64];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &periods, py);
            let dict = result.bind(py);
            let arr = dict.get_item("log_ret_1d").unwrap().unwrap();
            let slice = arr.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let vals = slice.readonly().as_slice().unwrap().to_vec();
            assert!(vals[0].is_nan());
            assert!((vals[1] - (101.0f64 / 100.0f64).ln()).abs() < 1e-6);
        });
    }

    #[test]
    fn test_log_returns_nan_for_insufficient_data() {
        let close = vec![100.0];
        let periods = vec![1i64];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &periods, py);
            let dict = result.bind(py);
            let arr = dict.get_item("log_ret_1d").unwrap().unwrap();
            let arr1 = arr.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            assert!(arr1.readonly().as_slice().unwrap()[0].is_nan());
        });
    }
}
