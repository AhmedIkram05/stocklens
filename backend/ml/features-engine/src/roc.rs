//! Compute Rate of Change (ROC).
//!
//! ROC[i] = ((close[i] / close[i-period]) - 1) * 100

use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

pub fn compute(close: &[f64], period: usize) -> Py<PyArray1<f64>> {
    let n = close.len();
    let mut result = crate::alloc_nans(n);

    for i in period..n {
        if close[i - period] != 0.0 {
            result[i] = ((close[i] / close[i - period]) - 1.0) * 100.0;
        }
        // else leave NaN (division by zero)
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
    fn test_roc_basic() {
        let close = vec![100.0, 105.0, 110.0, 115.0, 120.0, 125.0];

        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, 2);
            let arr = result.bind(py);
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            assert_eq!(vals.len(), 6);
            assert!(vals[0].is_nan());
            assert!(vals[1].is_nan());
            assert!((vals[2] - 10.0).abs() < 1e-10); // (110/100 - 1)*100 = 10%
            assert!((vals[3] - 9.5238).abs() < 1e-3); // (115/105 - 1)*100 ≈ 9.52%
        });
    }

    #[test]
    fn test_roc_period_longer_than_data() {
        let close = vec![100.0, 105.0];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, 5);
            let arr = result.bind(py);
            let vals = arr.readonly().as_slice().unwrap().to_vec();
            assert!(vals.iter().all(|x| x.is_nan()));
        });
    }
}
