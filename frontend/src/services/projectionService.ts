/**
 * ProjectionService
 *
 * Calculate CAGR and project future values using historical stock data
 * from the backend `/market/ohlcv/` endpoint. Also provides LSTM-based
 * directional predictions from the ML model.
 */

import { marketService, OHLCVData } from './market';
import { PRESET_RATES } from './stockPresets';
import { predictionService, PredictionResponse } from './prediction';
import { periodToStartDate } from '../constants/periods';

const CAGR_CACHE_TTL_MS = 5 * 60 * 1000;
const _cagrCache = new Map<string, { value: number | null; expires: number }>();
const _cagrInFlight = new Map<string, Promise<number | null>>();
let _cagrEpoch = 0;

/** Drop cached CAGRs (all, or one ticker) after underlying prices change. */
export function clearCAGRcache(ticker?: string): void {
  _cagrEpoch += 1;
  if (!ticker) {
    _cagrCache.clear();
    _cagrInFlight.clear();
    return;
  }
  const prefix = `${ticker.toUpperCase()}:`;
  for (const key of [..._cagrCache.keys(), ..._cagrInFlight.keys()]) {
    if (key.startsWith(prefix)) {
      _cagrCache.delete(key);
      _cagrInFlight.delete(key);
    }
  }
}

/**
 * Calculate CAGR from an arbitrary OHLCVData series using the actual span.
 *
 * @param series - Array of OHLCVData records
 * @returns CAGR as decimal or null if insufficient data
 */
export function computeCAGRFromSeries(series: OHLCVData[]): number | null {
  if (series.length < 2) return null;
  const first = series[0].adjusted_close;
  const last = series[series.length - 1].adjusted_close;
  if (!first || !last || first <= 0) return null;
  const years =
    (new Date(series[series.length - 1].date).getTime() - new Date(series[0].date).getTime()) /
    (1000 * 60 * 60 * 24 * 365.25);
  if (!(years > 0)) return null;
  return (last / first) ** (1 / years) - 1;
}

async function cachedCAGR(ticker: string, period: string): Promise<number | null> {
  const key = `${ticker.toUpperCase()}:${period}`;
  const hit = _cagrCache.get(key);
  if (hit && hit.expires > Date.now()) return hit.value;
  const pending = _cagrInFlight.get(key);
  if (pending) return pending;

  const epoch = _cagrEpoch;
  const request = (async () => {
    try {
      const ohlcv = await marketService.getOHLCV(ticker, periodToStartDate(period));
      const value = computeCAGRFromSeries(ohlcv);
      if (value !== null && epoch === _cagrEpoch) {
        _cagrCache.set(key, { value, expires: Date.now() + CAGR_CACHE_TTL_MS });
      }
      return value;
    } catch {
      return null;
    } finally {
      _cagrInFlight.delete(key);
    }
  })();

  _cagrInFlight.set(key, request);
  return request;
}

/**
 * Calculate CAGR over a lookback window (default 10 years).
 *
 * @param ticker - Stock ticker (e.g., 'AAPL')
 * @param period - Period label; defaults to 10Y
 * @returns CAGR as decimal (e.g., 0.15 = 15%) or null if insufficient data
 */
export async function getCAGR(ticker: string, period = '10Y'): Promise<number | null> {
  return cachedCAGR(ticker, period);
}

/**
 * Historical CAGR from today. Backed by the 10-year window (the backend caps
 * OHLCV rows, so "full history" is not available).
 */
export async function getHistoricalCAGRFromToday(ticker: string): Promise<number | null> {
  return getCAGR(ticker, '10Y');
}

/**
 * Get the historical CAGR for a ticker over a specific lookback window.
 *
 * Used for both historical and future projections so the growth rate reacts
 * to the selected year/period picker.
 *
 * @param ticker - Stock ticker
 * @param periodLabel - Period label (e.g., '3Y', '5Y') from PERIOD_OPTIONS
 * @returns CAGR as decimal over that window, or null if insufficient data
 */
export async function getHistoricalCAGRForPeriod(
  ticker: string,
  periodLabel: string,
): Promise<number | null> {
  return cachedCAGR(ticker, periodLabel);
}

/**
 * Project future value using historical CAGR with preset fallback.
 *
 * @param amount - Principal amount
 * @param symbol - Stock ticker
 * @param years - Number of years to project
 * @returns Object with CAGR rate and future value
 */
export async function projectUsingHistoricalCAGR(
  amount: number,
  symbol: string,
  years: number,
): Promise<{ rate: number; futureValue: number }> {
  const cagr = await getCAGR(symbol);
  const rate = cagr ?? PRESET_RATES[symbol.toUpperCase()] ?? 0.1;
  const futureValue = amount * Math.pow(1 + rate, years);
  return { rate, futureValue };
}

/**
 * Get LSTM-based directional prediction for a ticker.
 *
 * @param ticker - Stock ticker symbol
 * @returns PredictionResponse or null if unavailable
 */
export async function getLSTMPrediction(ticker: string): Promise<PredictionResponse | null> {
  try {
    return await predictionService.getPrediction(ticker);
  } catch {
    return null;
  }
}

/**
 * Get combined projection: LSTM direction + CAGR rate.
 * Uses LSTM as primary signal, CAGR as fallback growth rate.
 *
 * @param ticker - Stock ticker symbol
 * @returns Object with direction, rate, confidence, or null
 */
export async function getCombinedProjection(
  ticker: string,
  periodLabel?: string,
): Promise<{
  direction: 'UP' | 'FLAT' | 'DOWN';
  rate: number;
  confidence: number;
  model_version: string;
} | null> {
  try {
    const prediction = await predictionService.getPrediction(ticker);
    const rate = periodLabel
      ? await getHistoricalCAGRForPeriod(ticker, periodLabel)
      : await getCAGR(ticker, '10Y');
    return {
      direction: prediction.direction,
      rate: rate ?? 0.1,
      confidence: prediction.confidence,
      model_version: prediction.model_version,
    };
  } catch {
    // Fall back to CAGR-only
    const cagr = periodLabel
      ? await getHistoricalCAGRForPeriod(ticker, periodLabel)
      : await getCAGR(ticker, '10Y');
    if (cagr === null) return null;
    return {
      direction: cagr > 0 ? 'UP' : cagr < 0 ? 'DOWN' : 'FLAT',
      rate: cagr,
      confidence: 0.5,
      model_version: 'cagr-fallback',
    };
  }
}
