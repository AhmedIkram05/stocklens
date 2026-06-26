/**
 * DatabaseService
 *
 * SQLite initialization, schema management, and query helpers.
 */

import * as SQLite from 'expo-sqlite';

const db = SQLite.openDatabaseSync('stocklens_v2.db');

/**
 * DB_SCHEMAS - Table creation SQL statements
 *
 * Each schema uses CREATE TABLE IF NOT EXISTS for idempotent initialization.
 * Foreign keys are used to maintain referential integrity.
 */
export const DB_SCHEMAS = {
  users: `
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      uid TEXT NOT NULL UNIQUE,
      first_name TEXT,
      email TEXT NOT NULL UNIQUE,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      last_login DATETIME
    );
  `,
  receipts: `
    CREATE TABLE IF NOT EXISTS receipts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL,
      image_uri TEXT,
      total_amount REAL,
      date_scanned DATETIME DEFAULT CURRENT_TIMESTAMP,
      ocr_data TEXT,
      synced INTEGER DEFAULT 0,
      FOREIGN KEY (user_id) REFERENCES users (uid) ON DELETE CASCADE
    );
  `,
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
  user_settings: `
    CREATE TABLE IF NOT EXISTS user_settings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL UNIQUE,
      theme TEXT DEFAULT 'light',
      auto_backup INTEGER DEFAULT 0,
      FOREIGN KEY (user_id) REFERENCES users (uid) ON DELETE CASCADE
    );
  `,
  auth_state: `
    CREATE TABLE IF NOT EXISTS auth_state (
      key TEXT PRIMARY KEY,
      value TEXT
    );
  `,
};

/**
 * DB_INDEXES - Performance optimization indexes
 *
 * Indexes:
 * - idx_receipts_user_id_synced: Speed up queries filtering by user and sync status
 * - idx_receipts_date_scanned: Optimize date-based sorting (most recent first)
 * - idx_user_settings_user_id: Fast lookup of user preferences
 * - idx_alpha_cache_symbol_interval: Quick cache lookups for stock data
 */
const DB_INDEXES = [
  `CREATE INDEX IF NOT EXISTS idx_receipts_user_id_synced ON receipts (user_id, synced);`,
  `CREATE INDEX IF NOT EXISTS idx_receipts_date_scanned ON receipts (date_scanned DESC);`,
  `CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings (user_id);`,
  `CREATE INDEX IF NOT EXISTS idx_alpha_cache_symbol_interval ON alpha_cache (symbol, interval);`,
];

/**
 * Initialize database schema and indexes
 *
 * Process:
 * 1. Enables foreign key constraints
 * 2. Creates all tables (users, receipts, alpha_cache, user_settings, auth_state)
 * 3. Creates all indexes for performance
 * 4. Migrates schema if needed (adds ocr_data column if missing)
 *
 * @throws Error if database initialization fails
 *
 * Note: Safe to call multiple times (uses IF NOT EXISTS)
 */
export const initDatabase = async (): Promise<void> => {
  try {
    await db.execAsync('PRAGMA foreign_keys = ON;');

    for (const schema of Object.values(DB_SCHEMAS)) {
      await db.execAsync(schema);
    }

    for (const index of DB_INDEXES) {
      await db.execAsync(index);
    }
    try {
      const cols: any[] = await db.getAllAsync("PRAGMA table_info('receipts')");
      const hasOcr = cols.some((c) => c.name === 'ocr_data');
      if (!hasOcr) {
        try {
          await db.execAsync('ALTER TABLE receipts ADD COLUMN ocr_data TEXT;');
        } catch (e) {}
      }
    } catch (e) {}
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
