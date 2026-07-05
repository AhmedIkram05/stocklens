//! Compute On-Balance Volume (OBV).
//!
//! OBV[0] = 0
//! OBV[i] = OBV[i-1] + volume[i]  (if close[i] > close[i-1])
//! OBV[i] = OBV[i-1] - volume[i]  (if close[i] < close[i-1])
//! OBV[i] = OBV[i-1]              (if close[i] == close[i-1])

use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

pub fn compute(close: &[f64], volume: &[f64]) -> Py<PyArray1<f64>> {
    let n = close.len().min(volume.len());
    let mut result = crate::alloc_nans(n);

    if n == 0 {
        return make_array(result);
    }

    result[0] = 0.0;

    for i in 1..n {
        if close[i] > close[i - 1] {
            result[i] = result[i - 1] + volume[i];
        } else if close[i] < close[i - 1] {
            result[i] = result[i - 1] - volume[i];
        } else {
            result[i] = result[i - 1];
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
    fn test_obv_basic() {
        let close = vec![100.0, 102.0, 101.0, 103.0, 104.0];
        let volume = vec![1000.0, 1500.0, 1200.0, 1800.0, 2000.0];

        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &volume);
            let arr = result.bind(py);
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            assert_eq!(vals.len(), 5);
            assert_eq!(vals[0], 0.0);
            assert_eq!(vals[1], 1500.0);   // up → +1500
            assert_eq!(vals[2], 300.0);    // down → -1200
            assert_eq!(vals[3], 2100.0);   // up → +1800
            assert_eq!(vals[4], 4100.0);   // up → +2000
        });
    }

    #[test]
    fn test_obv_no_change() {
        let close = vec![100.0, 100.0, 100.0];
        let volume = vec![1000.0, 1000.0, 1000.0];

        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, &volume);
            let arr = result.bind(py);
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            assert_eq!(vals[0], 0.0);
            assert_eq!(vals[1], 0.0);  // no change, no addition
            assert_eq!(vals[2], 0.0);
        });
    }
}
