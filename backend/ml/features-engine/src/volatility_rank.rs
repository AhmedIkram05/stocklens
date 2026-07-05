//! Compute percentile rank of current volatility within a rolling window.

#![allow(clippy::needless_range_loop)]
use numpy::{PyArray1, ToPyArray};
use pyo3::prelude::*;

pub fn compute(close: &[f64], period: usize) -> Py<PyArray1<f64>> {
    let vol = crate::rolling_volatility::compute_raw(close, 30);
    let n = vol.len();
    let mut result = crate::alloc_nans(n);

    if n <= period {
        return make_array(result);
    }

    for i in period..n {
        let window_start = i - (period - 1);
        let current = vol[i];
        if current.is_nan() {
            continue;
        }
        let mut count_le = 0u32;
        for j in window_start..=i {
            if vol[j] <= current {
                count_le += 1;
            }
        }
        result[i] = count_le as f64 / (i - window_start + 1) as f64;
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
    fn test_volatility_rank_output_range() {
        use rand::Rng;
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        let mut prices = vec![100.0];
        for _ in 1..400 {
            let ret = (rng.gen::<f64>() - 0.5) * 0.06;
            prices.push(prices.last().unwrap() * (1.0 + ret));
        }
        let rank_result = compute(&prices, 252);
        Python::initialize();
        Python::attach(|py| {
            let arr = rank_result.bind(py);
            let ro = arr.readonly();
            let vals = ro.as_slice().unwrap();
            let finites: Vec<f64> = vals.iter().filter(|x| !x.is_nan()).copied().collect();
            assert!(!finites.is_empty());
            for &v in &finites {
                assert!(v >= 0.0 && v <= 1.0, "Rank {} out of [0, 1]", v);
            }
        });
    }
}
