/**
 * ProjectionService
 *
 * Calculate CAGR and project future values using historical stock data.
 */

import { stockService } from './dataService';
import { PRESET_RATES } from './stockPresets';

/**
 * Calculate CAGR from today backwards for a given number of years
 *
 * @param symbol - Stock ticker (e.g., 'AAPL', 'TSLA')
 * @param years - Number of years to look back
 * @returns CAGR as decimal (e.g., 0.15 = 15% annual return) or null if insufficient data
 *
 * Process:
 * 1. Fetches historical data via stockService (monthly for >1 year, daily for ≤1 year)
 * 2. Finds data point closest to (today - years)
 * 3. Calculates CAGR using start and end adjusted close prices
 * 4. Returns null if data is insufficient or invalid
 *
 * Edge Cases:
 * - If daily data fails for 1 year, tries monthly data (2 years) as fallback
 * - Uses adjustedClose if available (accounts for splits/dividends), else close
 * - Returns null for negative prices or invalid date ranges
 *
 * Formula:
 * CAGR = (lastPrice / firstPrice)^(1 / actualYears) - 1
 */
export async function getHistoricalCAGRFromToday(
  symbol: string,
  years: number,
): Promise<number | null> {
  try {
    const yearsInt = Math.max(1, Math.floor(Number(years) || 1));

    let data = null as any;
    try {
      data = await stockService.getHistoricalForTicker(symbol, yearsInt);
    } catch (e) {
      data = null;
    }

    if ((!data || data.length < 2) && yearsInt <= 1) {
      try {
        const monthly = await stockService.getHistoricalForTicker(symbol, 2);
        if (monthly && monthly.length >= 2) data = monthly;
      } catch (e) {}
    }

    if (!data || data.length < 2) return null;

    const now = new Date();
    const target = new Date(now);
    target.setFullYear(target.getFullYear() - yearsInt);

    let startEntry = data[0];
    for (let i = 0; i < data.length; i++) {
      const d = new Date(data[i].date);
      if (d <= target) startEntry = data[i];
      else break;
    }

    const endEntry = data[data.length - 1];
    const firstVal = (startEntry as any).adjustedClose ?? (startEntry as any).close;
    const lastVal = (endEntry as any).adjustedClose ?? (endEntry as any).close;
    if (!firstVal || !lastVal || firstVal <= 0) return null;

    const actualYears =
      (new Date(endEntry.date).getTime() - new Date(startEntry.date).getTime()) /
      (1000 * 60 * 60 * 24 * 365.25);
    if (!(actualYears > 0)) return null;

    // CAGR formula
    return Math.pow(lastVal / firstVal, 1 / actualYears) - 1;
  } catch (e) {
    return null;
  }
}

/**
 * Compute CAGR from a given time series
 *
 * @param series - Array of OHLCV records with date, adjustedClose, and close
 * @returns CAGR as decimal or null if insufficient data
 *
 * Process:
 * 1. Uses first and last entries from series
 * 2. Calculates time span in years
 * 3. Computes CAGR using start and end prices
 *
 * Formula:
 * CAGR = (lastPrice / firstPrice)^(1 / years) - 1
 *
 * Usage:
 * Useful for calculating returns from pre-fetched or cached data
 */
export function computeCAGRFromSeries(
  series: Array<{ date: string; adjustedClose?: number; close: number }>,
): number | null {
  if (!series || series.length < 2) return null;
  const first = series[0].adjustedClose ?? series[0].close;
  const last = series[series.length - 1].adjustedClose ?? series[series.length - 1].close;
  if (!first || !last || first <= 0) return null;
  const actualYears =
    (new Date(series[series.length - 1].date).getTime() - new Date(series[0].date).getTime()) /
    (1000 * 60 * 60 * 24 * 365.25);
  if (!(actualYears > 0)) return null;
  // CAGR formula
  return Math.pow(last / first, 1 / actualYears) - 1;
}

/**
 * Project future value using historical CAGR with preset fallback
 *
 * @param amount - Principal amount (receipt total)
 * @param symbol - Stock ticker (e.g., 'NVDA', 'MSFT')
 * @param years - Number of years to project forward
 * @returns Object with rate (CAGR) and futureValue
 *
 * Process:
 * 1. Attempts to fetch historical CAGR via getHistoricalCAGRFromToday
 * 2. If API data unavailable, falls back to PRESET_RATES[symbol]
 * 3. Calculates future value: amount * (1 + rate)^years
 *
 * Formula:
 * Future Value = principal * (1 + CAGR)^years
 *
 * Fallback:
 * - Uses PRESET_RATES if symbol exists (e.g., S&P 500 ≈ 10%)
 * - PRESET_RATES provide reasonable estimates for common stocks
 *
 * Usage:
 * Primary projection function used by ReceiptDetailsScreen and StockCard
 */
export async function projectUsingHistoricalCAGR(
  amount: number,
  symbol: string,
  years: number,
): Promise<{ rate: number; futureValue: number }> {
  const cagr = await getHistoricalCAGRFromToday(symbol, years);
  const rate = cagr ?? PRESET_RATES[symbol.toUpperCase()];
  const futureValue = amount * Math.pow(1 + rate, years);
  return { rate, futureValue };
}
