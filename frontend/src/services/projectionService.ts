/**
 * ProjectionService
 *
 * Calculate CAGR and project future values using historical stock data
 * from the backend `/market/ohlcv/` endpoint.
 */

import { marketService, OHLCVData } from './market';
import { PRESET_RATES } from './stockPresets';

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
