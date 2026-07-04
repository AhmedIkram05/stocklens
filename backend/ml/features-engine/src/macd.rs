//! Compute MACD (Moving Average Convergence Divergence).

use numpy::ToPyArray;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub fn compute(close: &[f64], fast: usize, slow: usize, signal: usize, py: Python<'_>) -> Py<PyDict> {
    let dict = PyDict::new(py);
    let n = close.len();

    let ema_fast = crate::ema(close, fast);
    let ema_slow = crate::ema(close, slow);

    let mut macd_line = crate::alloc_nans(n);
    let start = fast.max(slow) - 1;
    for i in start..n {
        if !ema_fast[i].is_nan() && !ema_slow[i].is_nan() {
            macd_line[i] = ema_fast[i] - ema_slow[i];
        }
    }

    let signal_line = crate::ema(&macd_line, signal);

    let mut hist = crate::alloc_nans(n);
    for i in 0..n {
        if !macd_line[i].is_nan() && !signal_line[i].is_nan() {
            hist[i] = macd_line[i] - signal_line[i];
        }
    }

    dict.set_item("macd", macd_line.to_pyarray(py)).unwrap();
    dict.set_item("macd_signal", signal_line.to_pyarray(py)).unwrap();
    dict.set_item("macd_hist", hist.to_pyarray(py)).unwrap();

    dict.into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use numpy::PyArrayMethods;
    use rand::SeedableRng;

    #[test]
    fn test_macd_output_shape() {
        use rand::Rng;
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        let mut prices = vec![100.0];
        for _ in 1..252 {
            let ret = (rng.gen::<f64>() - 0.5) * 0.06;
            prices.push(prices.last().unwrap() * (1.0 + ret));
        }
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&prices, 12, 26, 9, py);
            let dict = result.bind(py);
            assert!(dict.get_item("macd").unwrap().is_some());
            assert!(dict.get_item("macd_signal").unwrap().is_some());
            assert!(dict.get_item("macd_hist").unwrap().is_some());

            let macd = dict.get_item("macd").unwrap().unwrap();
            let arr = macd.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            assert_eq!(arr.readonly().as_slice().unwrap().len(), 252);
        });
    }

    #[test]
    fn test_macd_zero_for_flat() {
        let close = vec![100.0; 50];
        Python::initialize();
        Python::attach(|py| {
            let result = compute(&close, 12, 26, 9, py);
            let dict = result.bind(py);
            let macd = dict.get_item("macd").unwrap().unwrap();
            let arr = macd.extract::<Bound<'_, numpy::PyArray1<f64>>>().unwrap();
            let ro = arr.readonly();
            let slice = ro.as_slice().unwrap();
            let last_non_nan = slice.iter().filter(|x| !x.is_nan()).last().unwrap();
            assert!((*last_non_nan).abs() < 1e-6);
        });
    }
}
