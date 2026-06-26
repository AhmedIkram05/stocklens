/**
 * AlphaVantage Service
 *
 * Stock market data client with in-memory + SQLite caching and background refresh.
 */

import Constants from 'expo-constants';
import { emit } from './eventBus';
import { databaseService } from './database';

type MemCacheEntry = { value: any; expiresAt: number };
const serviceMemCache = new Map<string, MemCacheEntry>();

/**
 * Tracks in-flight background refresh requests to prevent duplicates
 */
const inFlightRefresh: Record<string, Promise<any> | undefined> = {};

export type OHLCV = {
  date: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  adjustedClose?: number;
  volume?: number;
};

/**
 * Alpha Vantage API base URL
 */
const API_BASE = 'https://www.alphavantage.co/query';

function getApiKey(): string {
  return (
    Constants.expoConfig?.extra?.EXPO_PUBLIC_ALPHA_VANTAGE_API_KEY ||
    process.env.EXPO_PUBLIC_ALPHA_VANTAGE_API_KEY ||
    process.env.ALPHA_VANTAGE_KEY ||
    ''
  );
}

async function fetchJson(url: string) {
  let lastErr: any = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`AlphaVantage HTTP error ${res.status}`);
      }
      const json = await res.json();
      if (json['Error Message']) {
        throw new Error(`AlphaVantage API Error: ${json['Error Message']}`);
      }
      if (json['Note']) {
        throw new Error(`AlphaVantage Note: ${json['Note']}`);
      }
      return json;
    } catch (err: any) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 250 * Math.pow(2, attempt)));
    }
  }
  throw lastErr;
}

function parseMonthlyAdjusted(json: any): OHLCV[] {
  const series = json['Monthly Adjusted Time Series'] || json['Monthly Time Series'];
  if (!series) throw new Error('Unexpected AlphaVantage monthly response');

  return Object.keys(series)
    .map((date) => {
      const row = series[date];
      return {
        date,
        open: parseFloat(row['1. open']),
        high: parseFloat(row['2. high']),
        low: parseFloat(row['3. low']),
        close: parseFloat(row['4. close']),
        adjustedClose: row['5. adjusted close'] ? parseFloat(row['5. adjusted close']) : undefined,
        volume: row['6. volume'] ? parseInt(row['6. volume'], 10) : undefined,
      } as OHLCV;
    })
    .sort((a, b) => (a.date > b.date ? 1 : -1));
}

function parseDailyAdjusted(json: any): OHLCV[] {
  const series =
    json['Time Series (Daily)'] || json['Daily Time Series'] || json['Time Series (Daily)'];
  if (!series) throw new Error('Unexpected AlphaVantage daily response');

  return Object.keys(series)
    .map((date) => {
      const row = series[date];
      return {
        date,
        open: parseFloat(row['1. open']),
        high: parseFloat(row['2. high']),
        low: parseFloat(row['3. low']),
        close: parseFloat(row['4. close']),
        adjustedClose: row['5. adjusted close'] ? parseFloat(row['5. adjusted close']) : undefined,
        volume: row['6. volume'] ? parseInt(row['6. volume'], 10) : undefined,
      } as OHLCV;
    })
    .sort((a, b) => (a.date > b.date ? 1 : -1));
}

export const alphaVantageService = {
  /** Get monthly adjusted OHLCV data for a stock symbol. */
  getMonthlyAdjusted: async (symbol: string): Promise<OHLCV[]> => {
    const cacheKey = `av:monthly:${symbol}`;
    // Try in-memory cache first
    const now = Date.now();
    const ttlMs = 30 * 24 * 60 * 60 * 1000; // 30 days for monthly
    const mem = serviceMemCache.get(cacheKey);
    if (mem && mem.expiresAt > now) return mem.value;
    // Try reading from persistent alpha_cache table
    try {
      const rows = await databaseService.executeQuery(
        'SELECT raw_json, fetched_at FROM alpha_cache WHERE symbol = ? AND interval = ? AND params = ? LIMIT 1',
        [symbol, 'monthly', ''],
      );
      if (rows && rows.length > 0) {
        const row = rows[0];
        const fetchedAt = row.fetched_at ? Date.parse(row.fetched_at) : null;
        if (fetchedAt && fetchedAt + ttlMs > now) {
          const json = JSON.parse(row.raw_json);
          const parsed = parseMonthlyAdjusted(json);
          serviceMemCache.set(cacheKey, { value: parsed, expiresAt: fetchedAt + ttlMs });
          try {
            emit('alpha_cache_hit', { symbol, interval: 'monthly' });
          } catch (e) {}
          return parsed;
        }
        if (fetchedAt) {
          try {
            const json = JSON.parse(row.raw_json);
            const parsed = parseMonthlyAdjusted(json);
            // stale: return parsed and trigger background refresh
            backgroundRefreshMonthly(symbol, cacheKey);
            serviceMemCache.set(cacheKey, { value: parsed, expiresAt: fetchedAt + ttlMs });
            try {
              emit('alpha_cache_hit', { symbol, interval: 'monthly', stale: true });
            } catch (e) {}
            return parsed;
          } catch (e) {
            // fallthrough to fetch
          }
        }
      }
    } catch (e) {
      // DB read failed — proceed to fetch from network
    }
    // no cache: fetch and store
    const key = getApiKey();
    if (!key)
      throw new Error(
        'Alpha Vantage API key not configured. Set ALPHA_VANTAGE_API_KEY in expo extra or environment.',
      );
    const url = `${API_BASE}?function=TIME_SERIES_MONTHLY_ADJUSTED&symbol=${encodeURIComponent(symbol)}&apikey=${encodeURIComponent(key)}`;
    const json = await fetchJson(url);
    const parsed = parseMonthlyAdjusted(json);
    // persist raw response to alpha_cache for durable storage
    try {
      await databaseService.executeNonQuery(
        `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
        [symbol, 'monthly', '', new Date().toISOString(), JSON.stringify(json)],
      );
    } catch (e) {
      // best-effort
    }
    serviceMemCache.set(cacheKey, { value: parsed, expiresAt: Date.now() + ttlMs });
    return parsed;
  },

  /** Read cached daily adjusted OHLCV from SQLite (offline). */
  getCachedDailyAdjusted: async (symbol: string): Promise<OHLCV[] | null> => {
    try {
      const rows = await databaseService.executeQuery(
        'SELECT raw_json, fetched_at FROM alpha_cache WHERE symbol = ? AND interval = ? AND params = ? LIMIT 1',
        [symbol, 'daily', ''],
      );
      if (!rows || rows.length === 0) return null;
      const row = rows[0];
      const json = JSON.parse(row.raw_json);
      const parsed = parseDailyAdjusted(json);
      try {
        emit('alpha_cache_hit', { symbol, interval: 'daily' });
      } catch (e) {}
      return parsed;
    } catch (e) {
      return null;
    }
  },

  /** Read cached monthly adjusted OHLCV from SQLite (offline). */
  getCachedMonthlyAdjusted: async (symbol: string): Promise<OHLCV[] | null> => {
    try {
      const rows = await databaseService.executeQuery(
        'SELECT raw_json, fetched_at FROM alpha_cache WHERE symbol = ? AND interval = ? AND params = ? LIMIT 1',
        [symbol, 'monthly', ''],
      );
      if (!rows || rows.length === 0) return null;
      const row = rows[0];
      const json = JSON.parse(row.raw_json);
      const parsed = parseMonthlyAdjusted(json);
      return parsed;
    } catch (e) {
      return null;
    }
  },

  /** Get daily adjusted OHLCV data for a stock symbol. */
  getDailyAdjusted: async (symbol: string): Promise<OHLCV[]> => {
    const cacheKey = `av:daily:${symbol}`;

    const now = Date.now();
    const ttlMs = 24 * 60 * 60 * 1000; // 24 hours
    const mem = serviceMemCache.get(cacheKey);
    if (mem && mem.expiresAt > now) return mem.value;

    try {
      const rows = await databaseService.executeQuery(
        'SELECT raw_json, fetched_at FROM alpha_cache WHERE symbol = ? AND interval = ? AND params = ? LIMIT 1',
        [symbol, 'daily', ''],
      );
      if (rows && rows.length > 0) {
        const row = rows[0];
        const fetchedAt = row.fetched_at ? Date.parse(row.fetched_at) : null;
        if (fetchedAt && fetchedAt + ttlMs > now) {
          const json = JSON.parse(row.raw_json);
          const parsed = parseDailyAdjusted(json);
          serviceMemCache.set(cacheKey, { value: parsed, expiresAt: fetchedAt + ttlMs });
          try {
            emit('alpha_cache_hit', { symbol, interval: 'daily' });
          } catch (e) {}
          return parsed;
        }
        if (fetchedAt) {
          try {
            const json = JSON.parse(row.raw_json);
            const parsed = parseDailyAdjusted(json);
            backgroundRefreshDaily(symbol, cacheKey);
            serviceMemCache.set(cacheKey, { value: parsed, expiresAt: fetchedAt + ttlMs });
            try {
              emit('alpha_cache_hit', { symbol, interval: 'daily', stale: true });
            } catch (e) {}
            return parsed;
          } catch (e) {
            // fallthrough
          }
        }
      }
    } catch (e) {
      // fallback to network
    }

    const key = getApiKey();
    if (!key)
      throw new Error(
        'Alpha Vantage API key not configured. Set ALPHA_VANTAGE_API_KEY in expo extra or environment.',
      );
    const url = `${API_BASE}?function=TIME_SERIES_DAILY_ADJUSTED&symbol=${encodeURIComponent(symbol)}&outputsize=full&apikey=${encodeURIComponent(key)}`;
    const json = await fetchJson(url);
    const parsed = parseDailyAdjusted(json);
    try {
      await databaseService.executeNonQuery(
        `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
        [symbol, 'daily', '', new Date().toISOString(), JSON.stringify(json)],
      );
    } catch (e) {
      // best-effort
    }
    serviceMemCache.set(cacheKey, { value: parsed, expiresAt: Date.now() + ttlMs });
    return parsed;
  },

  /** Get near-real-time stock quote (short TTL). */
  getQuote: async (symbol: string): Promise<{ price: number; timestamp?: string }> => {
    const key = getApiKey();
    if (!key)
      throw new Error(
        'Alpha Vantage API key not configured. Set ALPHA_VANTAGE_KEY in expo extra or environment.',
      );
    const cacheKey = `av:quote:${symbol}`;
    const now = Date.now();
    const ttlMs = 5 * 60 * 1000; // 5 minutes
    const mem = serviceMemCache.get(cacheKey);
    if (mem && mem.expiresAt > now) return mem.value;

    try {
      const rows = await databaseService.executeQuery(
        'SELECT raw_json, fetched_at FROM alpha_cache WHERE symbol = ? AND interval = ? AND params = ? LIMIT 1',
        [symbol, 'quote', ''],
      );
      if (rows && rows.length > 0) {
        const row = rows[0];
        const fetchedAt = row.fetched_at ? Date.parse(row.fetched_at) : null;
        if (fetchedAt && fetchedAt + ttlMs > now) {
          const json = JSON.parse(row.raw_json);
          const quote = json['Global Quote'] || json['01. symbol'] ? json : null;
          if (quote && (quote['05. price'] || quote['price'])) {
            const price = quote['05. price']
              ? parseFloat(quote['05. price'])
              : parseFloat(quote['price']);
            const timestamp = quote['07. latest trading day'] || undefined;
            const result = { price, timestamp };
            serviceMemCache.set(cacheKey, { value: result, expiresAt: fetchedAt + ttlMs });
            return result;
          }
        }
        if (fetchedAt) {
          try {
            const json = JSON.parse(row.raw_json);
            (async () => {
              try {
                const fetched = await (alphaVantageService as any).getQuoteFetchOnly(symbol);
                serviceMemCache.set(cacheKey, { value: fetched, expiresAt: Date.now() + ttlMs });
                // persist raw JSON
                try {
                  await databaseService.executeNonQuery(
                    `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
                    [symbol, 'quote', '', new Date().toISOString(), JSON.stringify(fetched)],
                  );
                } catch (e) {
                  /* ignore */
                }
              } catch (e) {
                // ignore
              }
            })();
            const quote = json['Global Quote'] || json['01. symbol'] ? json : null;
            if (quote && (quote['05. price'] || quote['price'])) {
              const price = quote['05. price']
                ? parseFloat(quote['05. price'])
                : parseFloat(quote['price']);
              const timestamp = quote['07. latest trading day'] || undefined;
              const result = { price, timestamp };
              serviceMemCache.set(cacheKey, { value: result, expiresAt: fetchedAt + ttlMs });
              return result;
            }
          } catch (e) {
            // fallthrough
          }
        }
      }
    } catch (e) {
      // fallback
    }

    const url = `${API_BASE}?function=GLOBAL_QUOTE&symbol=${encodeURIComponent(symbol)}&apikey=${encodeURIComponent(key)}`;
    const json = await fetchJson(url);
    const quote = json['Global Quote'] || json['01. symbol'] ? json : null;
    if (!quote || (!quote['05. price'] && !quote['price'])) {
      // Some variants may return different shapes
      const firstKey = Object.keys(json).find((k) => k.startsWith('Global Quote'));
      if (firstKey) {
        const q = json[firstKey];
        return { price: parseFloat(q['05. price']), timestamp: q['07. latest trading day'] };
      }
      throw new Error('Unexpected Global Quote response');
    }

    const price = quote['05. price'] ? parseFloat(quote['05. price']) : parseFloat(quote['price']);
    const timestamp =
      quote['07. latest trading day'] || quote['07. latest trading day'] || undefined;
    const result = { price, timestamp };
    // persist raw JSON
    try {
      await databaseService.executeNonQuery(
        `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
        [symbol, 'quote', '', new Date().toISOString(), JSON.stringify(json)],
      );
    } catch (e) {
      // best-effort
    }
    serviceMemCache.set(cacheKey, { value: result, expiresAt: Date.now() + ttlMs });
    return result;
  },
};

/** Background refresh helper for monthly data. */
async function backgroundRefreshMonthly(symbol: string, cacheKey: string) {
  try {
    if (inFlightRefresh[cacheKey]) return inFlightRefresh[cacheKey];
    inFlightRefresh[cacheKey] = (async () => {
      const key = getApiKey();
      const url = `${API_BASE}?function=TIME_SERIES_MONTHLY_ADJUSTED&symbol=${encodeURIComponent(symbol)}&apikey=${encodeURIComponent(key)}`;
      const json = await fetchJson(url);
      const parsed = parseMonthlyAdjusted(json);
      // persist raw JSON
      try {
        await databaseService.executeNonQuery(
          `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
          [symbol, 'monthly', '', new Date().toISOString(), JSON.stringify(json)],
        );
      } catch (e) {
        // ignore
      }
      serviceMemCache.set(cacheKey, {
        value: parsed,
        expiresAt: Date.now() + 30 * 24 * 60 * 60 * 1000,
      });
      emit('historical-updated', { symbol, interval: 'monthly' });
      delete inFlightRefresh[cacheKey];
    })();
    return inFlightRefresh[cacheKey];
  } catch (e) {
    delete inFlightRefresh[cacheKey];
    throw e;
  }
}

/** Background refresh helper for daily data. */
async function backgroundRefreshDaily(symbol: string, cacheKey: string) {
  try {
    if (inFlightRefresh[cacheKey]) return inFlightRefresh[cacheKey];
    inFlightRefresh[cacheKey] = (async () => {
      const key = getApiKey();
      const url = `${API_BASE}?function=TIME_SERIES_DAILY_ADJUSTED&symbol=${encodeURIComponent(symbol)}&outputsize=full&apikey=${encodeURIComponent(key)}`;
      const json = await fetchJson(url);
      const parsed = parseDailyAdjusted(json);
      // persist raw JSON
      try {
        await databaseService.executeNonQuery(
          `INSERT OR REPLACE INTO alpha_cache (symbol, interval, params, fetched_at, raw_json) VALUES (?, ?, ?, ?, ?)`,
          [symbol, 'daily', '', new Date().toISOString(), JSON.stringify(json)],
        );
      } catch (e) {
        // ignore
      }
      serviceMemCache.set(cacheKey, { value: parsed, expiresAt: Date.now() + 24 * 60 * 60 * 1000 });
      emit('historical-updated', { symbol, interval: 'daily' });
      delete inFlightRefresh[cacheKey];
    })();
    return inFlightRefresh[cacheKey];
  } catch (e) {
    delete inFlightRefresh[cacheKey];
    throw e;
  }
}

/** Internal helper for immediate quote fetch (used internally). */
(alphaVantageService as any).getQuoteFetchOnly = async (symbol: string) => {
  const key = getApiKey();
  const url = `${API_BASE}?function=GLOBAL_QUOTE&symbol=${encodeURIComponent(symbol)}&apikey=${encodeURIComponent(key)}`;
  const json = await fetchJson(url);
  const quote = json['Global Quote'] || json['01. symbol'] ? json : null;
  if (!quote || (!quote['05. price'] && !quote['price']))
    throw new Error('Unexpected Global Quote response');
  const price = quote['05. price'] ? parseFloat(quote['05. price']) : parseFloat(quote['price']);
  const timestamp = quote['07. latest trading day'] || undefined;
  return { price, timestamp };
};
