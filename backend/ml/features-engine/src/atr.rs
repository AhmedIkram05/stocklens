//! Compute Average True Range (ATR).
//!
//! TR = max(high - low, |high - prev_close|, |low - prev_close|)
//! ATR = SMA(TR, period)

use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

pub fn compute(high: &[f64], low: &[f64], close: &[f64], period: usize) -> Py<PyArray1<f64>> {
    let n = high.len().min(low.len()).min(close.len());
    let mut result = crate::alloc_nans(n);

    if n <= period {
        return make_array(result);
    }

    let mut tr_sum = 0.0;
    for i in 1..n {
        let hl = high[i] - low[i];
        let hc = (high[i] - close[i - 1]).abs();
        let lc = (low[i] - close[i - 1]).abs();
        let tr = hl.max(hc).max(lc);

        if i < period {
            tr_sum += tr;
        } else if i == period {
            tr_sum += tr;
            result[i] = tr_sum / period as f64;
        } else {
            // Moving average of TR: accumulate and slide
            let prev_tr = {
                let prev_hl = high[i - period] - low[i - period];
                let prev_hc = (high[i - period] - close[i - period - 1]).abs();
                let prev_lc = (low[i - period] - close[i - period - 1]).abs();
                prev_hl.max(prev_hc).max(prev_lc)
            };
            tr_sum += tr - prev_tr;
            result[i] = tr_sum / period as f64;
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
    fn test_atr_basic() {
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
            assert!(vals[2].is_nan());
            assert!(!vals[3].is_nan());
            assert!(!vals[6].is_nan());
            assert!(vals[3] > 0.0);
        });
    }
}
