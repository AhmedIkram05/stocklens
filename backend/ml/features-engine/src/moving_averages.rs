//! Compute simple moving averages using a ring buffer (O(n) per window).

use numpy::ToPyArray;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub fn compute(close: &[f64], windows: &[i64], py: Python<'_>) -> Py<PyDict> {
    let dict = PyDict::new(py);
    let n = close.len();

    for &w in windows {
        let window = w as usize;
        let mut result = crate::alloc_nans(n);
        if n >= window {
            let mut sum: f64 = close[..window].iter().sum();
            result[window - 1] = sum / window as f64;
            for i in window..n {
                sum += close[i] - close[i - window];
                result[i] = sum / window as f64;
            }
        }
        dict.set_item(format!("ma_{w}"), result.to_pyarray(py)).unwrap();
    }

    dict.into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use numpy::PyArrayMethods;


    #[test]
    fn test_sma_basic() {
        let close = vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &[3], py);
            let dict = result.bind(py);
            let arr = dict.get_item("ma_3").unwrap().unwrap();
            let slice = arr.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let ro = slice.readonly();
            let vals = ro.as_slice().unwrap();
            assert!((vals[2] - 2.0).abs() < 1e-10);
            assert!((vals[3] - 3.0).abs() < 1e-10);
            assert!(vals[0].is_nan());
            assert!(vals[1].is_nan());
        });
    }

    #[test]
    fn test_sma_not_enough_data() {
        let close = vec![1.0, 2.0];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &[5], py);
            let dict = result.bind(py);
            let arr = dict.get_item("ma_5").unwrap().unwrap();
            let arr1 = arr.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            assert!(arr1.readonly().as_slice().unwrap().iter().all(|x| x.is_nan()));
        });
    }
}
