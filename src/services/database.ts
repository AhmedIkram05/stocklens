/**
 * DatabaseService
 *
 * SQLite initialization for Alpha Vantage stock data cache only.
 *
 * Receipts, users, and settings now use the FastAPI backend.
 * This file is retained only for caching stock market data locally.
 */

import * as SQLite from 'expo-sqlite';

const db = SQLite.openDatabaseSync('stocklens_v2.db');

/**
 * DB_SCHEMAS - Table creation SQL statements
 *
 * Only alpha_cache remains for stock data caching.
 */
export const DB_SCHEMAS = {
  alpha_cache: `
    CREATE TABLE IF NOT EXISTS alpha_cache (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL,
      interval TEXT NOT NULL,
      params TEXT DEFAULT '',
      fetched_at DATETIME NOT NULL,
      raw_json TEXT NOT NULL,
      UNIQUE(symbol, interval, params)
    );
  `,
};

/**
 * DB_INDEXES - Performance optimization indexes
 *
 * Indexes:
 * - idx_alpha_cache_symbol_interval: Quick cache lookups for stock data
 */
const DB_INDEXES = [
  `CREATE INDEX IF NOT EXISTS idx_alpha_cache_symbol_interval ON alpha_cache (symbol, interval);`,
];

/**
 * Initialize database schema and indexes
 *
 * Process:
 * 1. Creates alpha_cache table for stock data caching
 * 2. Creates indexes for performance
 *
 * @throws Error if database initialization fails
 *
 * Note: Safe to call multiple times (uses IF NOT EXISTS)
 */
export const initDatabase = async (): Promise<void> => {
  try {
    for (const schema of Object.values(DB_SCHEMAS)) {
      await db.execAsync(schema);
    }

    for (const index of DB_INDEXES) {
      await db.execAsync(index);
    }
  } catch (error) {
    throw error;
  }
};

/**
 * databaseService - Query execution helpers
 *
 * Provides two core methods:
 * - executeQuery: For SELECT queries (returns rows)
 * - executeNonQuery: For INSERT/UPDATE/DELETE (returns affected count or last ID)
 * - pruneAlphaCacheOlderThan: Clean up old stock data cache entries
 */
export const databaseService = {
  /**
   * Execute a SELECT query and return all matching rows
   *
   * @param query - SQL query string (parameterized with ?)
   * @param params - Parameter values to bind to query
   * @returns Array of result rows
   */
  executeQuery: async (query: string, params: any[] = []): Promise<any[]> => {
    try {
      const result = await db.getAllAsync(query, params);
      return result;
    } catch (error) {
      throw error;
    }
  },

  /**
   * Execute an INSERT/UPDATE/DELETE query
   *
   * @param query - SQL query string (parameterized with ?)
   * @param params - Parameter values to bind to query
   * @returns For INSERT: lastInsertRowId, for UPDATE/DELETE: number of rows changed
   */
  executeNonQuery: async (query: string, params: any[] = []): Promise<number> => {
    try {
      const result = await db.runAsync(query, params);
      return result.lastInsertRowId || result.changes;
    } catch (error) {
      throw error;
    }
  },

  /**
   * Prune old Alpha Vantage cache entries
   *
   * @param days - Delete cache entries older than this many days
   *
   * Process:
   * - Calculates cutoff timestamp (current time - days)
   * - Deletes all alpha_cache rows fetched before cutoff
   * - Best-effort operation (errors are logged but not thrown)
   *
   * Usage: Call periodically to prevent unbounded cache growth
   */
  pruneAlphaCacheOlderThan: async (days: number) => {
    try {
      const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
      await databaseService.executeNonQuery(
        'DELETE FROM alpha_cache WHERE fetched_at IS NOT NULL AND fetched_at < ?',
        [cutoff],
      );
    } catch (e) {}
  },
};

export default db;
