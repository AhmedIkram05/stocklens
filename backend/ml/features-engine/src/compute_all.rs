//! Orchestrator: calls all 11 indicator functions, merges into a single PyDict.

use pyo3::prelude::*;
use pyo3::types::PyDict;

pub fn compute(close: &[f64], high: &[f64], low: &[f64], volume: &[f64], py: Python<'_>) -> Py<PyDict> {
    let dict = PyDict::new(py);

    // Log returns
    let lr = crate::log_returns::compute(close, &[1, 5, 21], py);
    let lr_dict = lr.bind(py);
    for key in &["log_ret_1d", "log_ret_5d", "log_ret_21d"] {
        if let Some(val) = lr_dict.get_item(*key).unwrap() {
            dict.set_item(*key, val).unwrap();
        }
    }

    // Moving averages
    let ma = crate::moving_averages::compute(close, &[5, 10, 20, 50], py);
    let ma_dict = ma.bind(py);
    for key in &["ma_5", "ma_10", "ma_20", "ma_50"] {
        if let Some(val) = ma_dict.get_item(*key).unwrap() {
            dict.set_item(*key, val).unwrap();
        }
    }

    // RSI(14)
    let rsi = crate::rsi::compute(close, 14);
    dict.set_item("rsi_14", rsi.bind(py)).unwrap();

    // MACD(12,26,9)
    let macd = crate::macd::compute(close, 12, 26, 9, py);
    let macd_dict = macd.bind(py);
    for key in &["macd", "macd_signal", "macd_hist"] {
        if let Some(val) = macd_dict.get_item(*key).unwrap() {
            dict.set_item(*key, val).unwrap();
        }
    }

    // Rolling volatility(30)
    let vol = crate::rolling_volatility::compute(close, 30);
    dict.set_item("vol_30d", vol.bind(py)).unwrap();

    // Volatility rank(252)
    let rank = crate::volatility_rank::compute(close, 252);
    dict.set_item("vol_rank", rank.bind(py)).unwrap();

    // Bollinger Bands(20, 2.0)
    let bb = crate::bollinger::compute(close, 20, 2.0, py);
    let bb_dict = bb.bind(py);
    for key in &["bb_pctb", "bb_width"] {
        if let Some(val) = bb_dict.get_item(*key).unwrap() {
            dict.set_item(*key, val).unwrap();
        }
    }

    // ATR(14)
    let atr = crate::atr::compute(high, low, close, 14);
    dict.set_item("atr_14", atr.bind(py)).unwrap();

    // OBV
    let obv = crate::obv::compute(close, volume);
    dict.set_item("obv", obv.bind(py)).unwrap();

    // Williams %R(14)
    let wr = crate::williams_r::compute(high, low, close, 14);
    dict.set_item("williams_r_14", wr.bind(py)).unwrap();

    // ROC(10)
    let roc = crate::roc::compute(close, 10);
    dict.set_item("roc_10", roc.bind(py)).unwrap();

    dict.into()
}
