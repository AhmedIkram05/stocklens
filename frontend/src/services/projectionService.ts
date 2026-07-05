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

/**
 * Calculate CAGR from backend OHLCV data for a ticker.
 *
 * @param ticker - Stock ticker (e.g., 'AAPL')
 * @returns CAGR as decimal (e.g., 0.15 = 15%) or null if insufficient data
 */
export async function getCAGR(ticker: string): Promise<number | null> {
  try {
    const ohlcv = await marketService.getOHLCV(ticker);
    if (ohlcv.length < 2) return null;
    const first = ohlcv[0].adjusted_close;
    const last = ohlcv[ohlcv.length - 1].adjusted_close;
    if (!first || !last || first <= 0) return null;
    const years =
      (new Date(ohlcv[ohlcv.length - 1].date).getTime() - new Date(ohlcv[0].date).getTime()) /
      (1000 * 60 * 60 * 24 * 365.25);
    if (!(years > 0)) return null;
    return (last / first) ** (1 / years) - 1;
  } catch {
    return null;
  }
}

/**
 * Calculate CAGR from an arbitrary OHLCVData series.
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

/**
 * Get the historical CAGR for a ticker from the backend.
 * This is a backward-compatible alias used by ReceiptDetailsScreen.
 *
 * @param ticker - Stock ticker
 * @returns CAGR as decimal, or null if insufficient data
 */
export async function getHistoricalCAGRFromToday(ticker: string): Promise<number | null> {
  return getCAGR(ticker);
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
export async function getCombinedProjection(ticker: string): Promise<{
  direction: 'UP' | 'FLAT' | 'DOWN';
  rate: number;
  confidence: number;
  model_version: string;
} | null> {
  try {
    const [prediction, cagr] = await Promise.all([
      predictionService.getPrediction(ticker),
      getCAGR(ticker),
    ]);
    return {
      direction: prediction.direction,
      rate: cagr ?? 0.1,
      confidence: prediction.confidence,
      model_version: prediction.model_version,
    };
  } catch {
    // Fall back to CAGR-only
    const cagr = await getCAGR(ticker);
    if (cagr === null) return null;
    return {
      direction: cagr > 0 ? 'UP' : cagr < 0 ? 'DOWN' : 'FLAT',
      rate: cagr,
      confidence: 0.5,
      model_version: 'cagr-fallback',
    };
  }
}
