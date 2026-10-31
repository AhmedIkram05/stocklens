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
        if window > 0 && n >= window {
            // Running sum plus a NaN count: a NaN in the window makes that
            // output NaN, and the count lets the sum recover once the bad
            // value leaves — a NaN can never be subtracted back out.
            let mut sum: f64 = 0.0;
            let mut nan_count = 0usize;
            for value in &close[..window] {
                if value.is_nan() {
                    nan_count += 1;
                } else {
                    sum += value;
                }
            }
            if nan_count == 0 {
                result[window - 1] = sum / window as f64;
            }
            for i in window..n {
                let outgoing = close[i - window];
                if outgoing.is_nan() {
                    nan_count -= 1;
                } else {
                    sum -= outgoing;
                }
                let incoming = close[i];
                if incoming.is_nan() {
                    nan_count += 1;
                } else {
                    sum += incoming;
                }
                if nan_count == 0 {
                    result[i] = sum / window as f64;
                }
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

    #[test]
    fn test_sma_recovers_after_nan() {
        // A single NaN must not poison the ring-buffer sum forever: the window
        // is NaN while it contains the bad value, then recovers.
        let close = vec![1.0, 2.0, f64::NAN, 4.0, 5.0, 6.0, 7.0];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &[3], py);
            let dict = result.bind(py);
            let arr = dict.get_item("ma_3").unwrap().unwrap();
            let slice = arr.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let ro = slice.readonly();
            let vals = ro.as_slice().unwrap();
            assert!(vals[2].is_nan());
            assert!(vals[3].is_nan());
            assert!(vals[4].is_nan());
            assert!((vals[5] - 5.0).abs() < 1e-10); // [4, 5, 6]
            assert!((vals[6] - 6.0).abs() < 1e-10); // [5, 6, 7]
        });
    }
}
