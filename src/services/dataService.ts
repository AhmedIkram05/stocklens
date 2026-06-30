/**
 * DataService
 *
 * Stock market data access and cache prefetching.
 *
 * Receipts, users, and settings now use the FastAPI backend
 * (see receipts.ts, auth.ts, api.ts).
 */

import { databaseService } from './database';
import { alphaVantageService, OHLCV } from './alphaVantageService';

/**
 * stockService - Stock market data fetching
 *
 * Methods:
 * - getHistoricalForTicker: Fetch historical OHLCV data (delegates to alphaVantageService)
 * - getQuote: Fetch real-time quote (delegates to alphaVantageService)
 *
 * Integration:
 * - Uses alphaVantageService with automatic caching
 * - Switches between daily (≤1 year) and monthly (>1 year) data
 */
export const stockService = {
  /**
   * Get historical stock data for a ticker symbol
   *
   * @param symbol - Stock ticker (e.g., 'AAPL', 'TSLA')
   * @param years - Number of years of historical data to fetch
   * @returns Array of OHLCV records
   *
   * Strategy:
   * - years ≤ 1: Fetches daily adjusted data, filters to 1 year
   * - years > 1: Fetches monthly adjusted data, returns last (years * 12) months
   */
  getHistoricalForTicker: async (symbol: string, years = 5): Promise<OHLCV[]> => {
    try {
      if (years <= 1) {
        const daily = await alphaVantageService.getDailyAdjusted(symbol);
        const cutoff = new Date();
        cutoff.setFullYear(cutoff.getFullYear() - 1);
        return daily.filter((d) => new Date(d.date) >= cutoff);
      } else {
        const monthly = await alphaVantageService.getMonthlyAdjusted(symbol);
        const monthsNeeded = Math.max(12 * years, 12);
        return monthly.slice(-monthsNeeded);
      }
    } catch (error: any) {
      throw new Error(`Failed to fetch historical data for ${symbol}: ${error?.message || error}`);
    }
  },

  /**
   * Get real-time quote for a ticker symbol
   *
   * @param symbol - Stock ticker
   * @returns Quote object with current price and metadata
   */
  getQuote: async (symbol: string) => {
    try {
      return await alphaVantageService.getQuote(symbol);
    } catch (error: any) {
      throw new Error(`Failed to fetch quote for ${symbol}: ${error?.message || error}`);
    }
  },
};

/**
 * Prefetch marker symbol for tracking prefetch completion
 */
const PREFETCH_MARKER_SYMBOL = '__stocklens_prefetch_done__';

/**
 * Popular stock tickers to prefetch on app start
 */
export const PREFETCH_TICKERS = [
  'NVDA',
  'AAPL',
  'MSFT',
  'TSLA',
  'NKE',
  'AMZN',
  'GOOGL',
  'META',
  'JPM',
  'UNH',
];

/**
 * Ensure historical data is prefetched for popular stocks
 *
 * Best-effort operation (errors swallowed to not block app start).
 */
async function ensureHistoricalPrefetch() {
  try {
    const rows = await databaseService.executeQuery(
      'SELECT * FROM alpha_cache WHERE symbol = ? LIMIT 1',
      [PREFETCH_MARKER_SYMBOL],
    );
    if (rows && rows.length > 0) return;

    for (const t of PREFETCH_TICKERS) {
      try {
        await alphaVantageService.getMonthlyAdjusted(t);
      } catch (e) {}
    }

    try {
      await databaseService.executeNonQuery(
        `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
        [
          PREFETCH_MARKER_SYMBOL,
          'meta',
          '',
          new Date().toISOString(),
          JSON.stringify({ done: true }),
        ],
      );
    } catch (e) {}
  } catch (e) {}
}

export { ensureHistoricalPrefetch };

/**
 * Force a fresh prefetch by clearing marker and re-running
 */
export async function forceHistoricalPrefetch(): Promise<void> {
  try {
    await databaseService.executeNonQuery('DELETE FROM alpha_cache WHERE symbol = ?', [
      PREFETCH_MARKER_SYMBOL,
    ]);
  } catch (e) {}
  try {
    await ensureHistoricalPrefetch();
  } catch (e) {}
}
