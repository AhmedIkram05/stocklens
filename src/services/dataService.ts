/**
 * DataService
 *
 * High-level data access for receipts, users, settings and stocks.
 */

import { databaseService } from './database';
import { alphaVantageService, OHLCV } from './alphaVantageService';
import { emit } from './eventBus';
import keyManager from './keyManager';
import { isEncryptedPayload, decryptString, encryptString } from '@/utils/crypto';
import fileCrypto from '@/utils/fileCrypto';

/**
 * Receipt type - Represents a scanned receipt record
 *
 * @property id - Auto-incremented primary key
 * @property user_id - Firebase user UID (foreign key)
 * @property image_uri - Local file path to receipt image
 * @property total_amount - Extracted amount from OCR
 * @property date_scanned - ISO timestamp of scan
 * @property ocr_data - Raw OCR text from receipt
 * @property synced - 0 = pending Firestore sync, 1 = synced
 */
export interface Receipt {
  id?: number;
  user_id: string;
  image_uri?: string;
  total_amount?: number;
  date_scanned?: string;
  ocr_data?: string;
  synced?: number;
}

/**
 * UserSettings type - User preference record
 *
 * @property id - Auto-incremented primary key
 * @property user_id - Firebase user UID (foreign key)
 * @property theme - 'light' or 'dark'
 * @property auto_backup - 0 = disabled, 1 = enabled
 */
export interface UserSettings {
  id?: number;
  user_id: string;
  theme?: string;
  auto_backup?: number;
}

/**
 * receiptService - Receipt CRUD operations
 *
 * Methods:
 * - create: Insert new receipt record
 * - getByUserId: Fetch all receipts for a user (sorted newest first)
 * - getById: Fetch single receipt by ID
 * - update: Update receipt fields (partial update supported)
 * - delete: Delete single receipt
 * - deleteAll: Delete all receipts (optionally filtered by user)
 * - getUnsynced: Fetch receipts pending Firestore sync
 * - markAsSynced: Set synced flag to 1
 */
export const receiptService = {
  /**
   * Create a new receipt record
   *
   * @param receipt - Receipt object with user_id, image_uri, total_amount, ocr_data
   * @returns Newly inserted receipt ID
   */
  create: async (receipt: Receipt): Promise<number> => {
    // encrypt ocr_data and image file before saving (works for new writes only)
    let imageUri = receipt.image_uri;
    if (imageUri) {
      try {
        imageUri = await fileCrypto.encryptImageFile(imageUri);
      } catch (e) {}
    }

    let ocr = receipt.ocr_data || '';
    let totalAmountToStore: any = receipt.total_amount;
    try {
      const key = await keyManager.getOrCreateKey();
      ocr = await encryptString(ocr, key);
      if (receipt.total_amount !== undefined && receipt.total_amount !== null) {
        totalAmountToStore = await encryptString(String(receipt.total_amount), key);
      }
    } catch (e) {
      // on error, fall back to plaintext
      totalAmountToStore = receipt.total_amount;
    }

    const query = `
      INSERT INTO receipts (user_id, image_uri, total_amount, ocr_data, synced)
      VALUES (?, ?, ?, ?, ?)
    `;
    const params = [receipt.user_id, imageUri, totalAmountToStore, ocr, receipt.synced || 0];
    const id = await databaseService.executeNonQuery(query, params);
    return id;
  },

  /**
   * Get all receipts for a specific user
   *
   * @param userId - Firebase user UID
   * @returns Array of receipts sorted by date_scanned DESC (newest first)
   */
  getByUserId: async (userId: string): Promise<Receipt[]> => {
    const query = 'SELECT * FROM receipts WHERE user_id = ? ORDER BY date_scanned DESC';
    const rows = await databaseService.executeQuery(query, [userId]);
    // attempt to decrypt ocr_data and image files for display (newly encrypted rows only)
    try {
      const key = await keyManager.getOrCreateKey();
      // Parallelise per-row decryption to avoid sequential awaiting that delays UI
      await Promise.all(
        rows.map(async (r: any) => {
          if (r?.ocr_data && typeof r.ocr_data === 'string' && isEncryptedPayload(r.ocr_data)) {
            try {
              r.ocr_data = await decryptString(r.ocr_data, key);
            } catch (e) {}
          }
          // keep image_uri as stored (decryption is deferred to the UI to avoid blocking)
          // decrypt total_amount if stored encrypted
          if (
            r?.total_amount &&
            typeof r.total_amount === 'string' &&
            isEncryptedPayload(r.total_amount)
          ) {
            try {
              const dec = await decryptString(r.total_amount, key);
              const num = parseFloat(dec);
              r.total_amount = Number.isFinite(num) ? num : undefined;
            } catch (e) {}
          }
          // decrypt date_scanned if stored encrypted
          if (
            r?.date_scanned &&
            typeof r.date_scanned === 'string' &&
            isEncryptedPayload(r.date_scanned)
          ) {
            try {
              r.date_scanned = await decryptString(r.date_scanned, key);
            } catch (e) {}
          }
        }),
      );
    } catch (e) {}
    return rows;
  },

  /**
   * Get a single receipt by its ID
   *
   * @param id - Receipt primary key
   * @returns Receipt object or null if not found
   */
  getById: async (id: number): Promise<Receipt | null> => {
    const query = 'SELECT * FROM receipts WHERE id = ?';
    const results = await databaseService.executeQuery(query, [id]);
    if (results.length === 0) return null;
    const r = results[0];
    try {
      const key = await keyManager.getOrCreateKey();
      if (r?.ocr_data && typeof r.ocr_data === 'string' && isEncryptedPayload(r.ocr_data)) {
        try {
          r.ocr_data = await decryptString(r.ocr_data, key);
        } catch (e) {}
      }
      // keep image_uri as stored (decryption is deferred to the UI to avoid blocking)
      if (
        r?.total_amount &&
        typeof r.total_amount === 'string' &&
        isEncryptedPayload(r.total_amount)
      ) {
        try {
          const dec = await decryptString(r.total_amount, key);
          const num = parseFloat(dec);
          r.total_amount = Number.isFinite(num) ? num : undefined;
        } catch (e) {}
      }
      if (
        r?.date_scanned &&
        typeof r.date_scanned === 'string' &&
        isEncryptedPayload(r.date_scanned)
      ) {
        try {
          r.date_scanned = await decryptString(r.date_scanned, key);
        } catch (e) {}
      }
    } catch (e) {}
    return r;
  },

  /**
   * Update receipt fields (partial update)
   *
   * @param id - Receipt ID to update
   * @param receipt - Partial receipt object with fields to update
   *
   * Process:
   * - Filters out invalid/undefined fields
   * - Builds dynamic SET clause
   * - Executes UPDATE query
   *
   * Allowed fields: user_id, image_uri, total_amount, date_scanned, ocr_data, synced
   */
  update: async (id: number, receipt: Partial<Receipt>): Promise<void> => {
    const allowedFields: Array<keyof Receipt> = [
      'user_id',
      'image_uri',
      'total_amount',
      'date_scanned',
      'ocr_data',
      'synced',
    ];
    const fields = Object.keys(receipt).filter(
      (key) =>
        allowedFields.includes(key as keyof Receipt) && receipt[key as keyof Receipt] !== undefined,
    );
    if (fields.length === 0) {
      return;
    }
    const values = fields.map((key) => receipt[key as keyof Receipt]);
    const setClause = fields.map((field) => `${field} = ?`).join(', ');

    const query = `UPDATE receipts SET ${setClause} WHERE id = ?`;
    values.push(id);

    // encrypt any ocr_data or image_uri in the update values
    try {
      const key = await keyManager.getOrCreateKey();
      for (let i = 0; i < fields.length; i++) {
        const f = fields[i];
        const raw = values[i];
        if (f === 'ocr_data' && typeof raw === 'string') {
          try {
            values[i] = await encryptString(raw, key);
          } catch (e) {}
        }
        if (f === 'total_amount' && (typeof raw === 'number' || typeof raw === 'string')) {
          try {
            values[i] = await encryptString(String(raw), key);
          } catch (e) {}
        }
        if (f === 'date_scanned' && typeof raw === 'string') {
          try {
            values[i] = await encryptString(raw, key);
          } catch (e) {}
        }
        if (f === 'image_uri' && typeof raw === 'string' && raw.length > 0) {
          try {
            values[i] = await fileCrypto.encryptImageFile(raw);
          } catch (e) {}
        }
      }
    } catch (e) {}

    await databaseService.executeNonQuery(query, values);
  },

  /**
   * Delete a single receipt by ID
   *
   * @param id - Receipt ID to delete
   */
  delete: async (id: number): Promise<void> => {
    const query = 'DELETE FROM receipts WHERE id = ?';
    await databaseService.executeNonQuery(query, [id]);
  },

  /**
   * Delete all receipts (optionally filtered by user)
   *
   * @param userId - Optional Firebase user UID to filter deletion
   *
   * Process:
   * - If userId provided: Delete only that user's receipts
   * - If userId omitted: Delete ALL receipts (use with caution)
   * - Emits 'receipts-changed' event after deletion
   */
  deleteAll: async (userId?: string): Promise<void> => {
    if (userId) {
      const query = 'DELETE FROM receipts WHERE user_id = ?';
      await databaseService.executeNonQuery(query, [userId]);
    } else {
      const query = 'DELETE FROM receipts';
      await databaseService.executeNonQuery(query, []);
    }
    try {
      emit('receipts-changed', { userId });
    } catch (e) {}
  },

  /**
   * Get all unsynced receipts for a user
   *
   * @param userId - Firebase user UID
   * @returns Array of receipts with synced = 0
   *
   * Usage: Used by sync service to identify receipts pending Firestore upload
   */
  getUnsynced: async (userId: string): Promise<Receipt[]> => {
    const query = 'SELECT * FROM receipts WHERE user_id = ? AND synced = 0';
    const rows = await databaseService.executeQuery(query, [userId]);
    try {
      const key = await keyManager.getOrCreateKey();
      await Promise.all(
        rows.map(async (r: any) => {
          if (r?.ocr_data && typeof r.ocr_data === 'string' && isEncryptedPayload(r.ocr_data)) {
            try {
              r.ocr_data = await decryptString(r.ocr_data, key);
            } catch (e) {}
          }
          // keep image_uri as stored (decryption is deferred to the UI to avoid blocking)
          if (
            r?.total_amount &&
            typeof r.total_amount === 'string' &&
            isEncryptedPayload(r.total_amount)
          ) {
            try {
              const dec = await decryptString(r.total_amount, key);
              const num = parseFloat(dec);
              r.total_amount = Number.isFinite(num) ? num : undefined;
            } catch (e) {}
          }
          if (
            r?.date_scanned &&
            typeof r.date_scanned === 'string' &&
            isEncryptedPayload(r.date_scanned)
          ) {
            try {
              r.date_scanned = await decryptString(r.date_scanned, key);
            } catch (e) {}
          }
        }),
      );
    } catch (e) {}
    return rows;
  },

  /**
   * Mark a receipt as synced to Firestore
   *
   * @param id - Receipt ID to mark as synced
   *
   * Process: Sets synced = 1 for the specified receipt
   */
  markAsSynced: async (id: number): Promise<void> => {
    const query = 'UPDATE receipts SET synced = 1 WHERE id = ?';
    await databaseService.executeNonQuery(query, [id]);
  },
};

/**
 * settingsService - User settings CRUD operations
 *
 * Methods:
 * - upsert: Insert or update user settings
 * - getByUserId: Fetch settings for a user
 */
export const settingsService = {
  /**
   * Insert or update user settings
   *
   * @param settings - UserSettings object with user_id, theme, auto_backup
   *
   * Process: Uses INSERT OR REPLACE to upsert settings record
   */
  upsert: async (settings: UserSettings): Promise<void> => {
    // encrypt theme before storing (backwards-compatible: decrypt attempted on read)
    let theme = settings.theme || 'light';
    try {
      const key = await keyManager.getOrCreateKey();
      theme = await encryptString(theme, key);
    } catch (e) {
      // fall back to plaintext on error
    }

    const query = `
      INSERT OR REPLACE INTO user_settings (user_id, theme, auto_backup)
      VALUES (?, ?, ?)
    `;
    const params = [settings.user_id, theme, settings.auto_backup || 0];
    await databaseService.executeNonQuery(query, params);
  },

  /**
   * Get user settings by user ID
   *
   * @param userId - Firebase user UID
   * @returns UserSettings object or null if not found
   */
  getByUserId: async (userId: string): Promise<UserSettings | null> => {
    const query = 'SELECT * FROM user_settings WHERE user_id = ?';
    const results = await databaseService.executeQuery(query, [userId]);
    if (results.length === 0) return null;
    const r = results[0];
    try {
      const key = await keyManager.getOrCreateKey();
      if (r?.theme && typeof r.theme === 'string' && isEncryptedPayload(r.theme)) {
        try {
          r.theme = await decryptString(r.theme, key);
        } catch (e) {}
      }
    } catch (e) {}
    return r;
  },
};

/**
 * userService - User profile CRUD operations
 *
 * Methods:
 * - upsert: Insert or update user record (handles UID/email conflicts)
 * - getByUid: Fetch user by Firebase UID
 * - deleteByUid: Delete user and cascade to related records
 */
export const userService = {
  /**
   * Insert or update user profile
   *
   * @param uid - Firebase user UID
   * @param firstName - User's first name (nullable)
   * @param email - User's email address
   * @returns Number of rows affected or last insert ID
   *
   * Process:
   * 1. Attempts INSERT with ON CONFLICT(uid) DO UPDATE
   * 2. If email UNIQUE constraint fails, updates existing user with same email
   * 3. Updates last_login timestamp on every call
   *
   * Edge Cases:
   * - Handles user UID changes (e.g., account re-creation with same email)
   * - Maintains referential integrity with receipts and settings
   */
  upsert: async (uid: string, firstName: string | null, email: string): Promise<number> => {
    const timestamp = new Date().toISOString();

    try {
      // encrypt firstName and email before storing
      let encFirstName = firstName;
      let encEmail = email;
      if (firstName !== null && firstName !== undefined) {
        try {
          const key = await keyManager.getOrCreateKey();
          encFirstName = await encryptString(firstName, key);
        } catch (e) {
          // fall back to plaintext
          encFirstName = firstName;
        }
      }

      try {
        const key2 = await keyManager.getOrCreateKey();
        encEmail = await encryptString(email, key2);
      } catch (e) {
        encEmail = email;
      }

      const query = `
        INSERT INTO users (uid, first_name, email, last_login)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(uid) DO UPDATE SET
          first_name = excluded.first_name,
          email = excluded.email,
          last_login = excluded.last_login
      `;
      const params = [uid, encFirstName, encEmail, timestamp];
      return await databaseService.executeNonQuery(query, params);
    } catch (error: any) {
      if (error?.message?.includes('UNIQUE constraint failed: users.email')) {
        const updateQuery = `
          UPDATE users
          SET uid = ?, first_name = ?, last_login = ?
          WHERE email = ?
        `;
        // encrypt firstName for the update branch as well
        let encFirstName2 = firstName;
        if (firstName !== null && firstName !== undefined) {
          try {
            const key = await keyManager.getOrCreateKey();
            encFirstName2 = await encryptString(firstName, key);
          } catch (e) {
            encFirstName2 = firstName;
          }
        }
        // encrypt email for update branch as well
        let encEmail2 = email;
        try {
          const key3 = await keyManager.getOrCreateKey();
          encEmail2 = await encryptString(email, key3);
        } catch (e) {
          encEmail2 = email;
        }
        return await databaseService.executeNonQuery(updateQuery, [
          uid,
          encFirstName2,
          timestamp,
          encEmail2,
        ]);
      }

      throw error;
    }
  },

  /**
   * Get user profile by Firebase UID
   *
   * @param uid - Firebase user UID
   * @returns User object or null if not found
   */
  getByUid: async (uid: string) => {
    const query = 'SELECT * FROM users WHERE uid = ?';
    const results = await databaseService.executeQuery(query, [uid]);
    if (results.length === 0) return null;
    const r = results[0];
    try {
      const key = await keyManager.getOrCreateKey();
      if (r?.first_name && typeof r.first_name === 'string' && isEncryptedPayload(r.first_name)) {
        try {
          r.first_name = await decryptString(r.first_name, key);
        } catch (e) {}
      }
      if (r?.email && typeof r.email === 'string' && isEncryptedPayload(r.email)) {
        try {
          r.email = await decryptString(r.email, key);
        } catch (e) {}
      }
    } catch (e) {}
    return r;
  },

  /**
   * Delete user profile by Firebase UID
   *
   * @param uid - Firebase user UID
   *
   * Note: Foreign key CASCADE will delete related receipts and settings
   */
  deleteByUid: async (uid: string) => {
    const query = 'DELETE FROM users WHERE uid = ?';
    await databaseService.executeNonQuery(query, [uid]);
  },
};

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
   *
   * Usage: Called by projectionService to calculate CAGR
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
 *
 * Tickers: NVDA, AAPL, MSFT, TSLA, NKE, AMZN, GOOGL, META, JPM, UNH
 * Reduces latency when users view investment projections
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
 * Process:
 * 1. Checks if prefetch marker exists in alpha_cache
 * 2. If not found: Fetches monthly data for all PREFETCH_TICKERS
 * 3. Inserts prefetch marker to prevent redundant fetches
 *
 * Usage: Called once on app initialization (see App.tsx)
 *
 * Note: Best-effort operation (errors are swallowed to not block app start)
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
 *
 * Process:
 * 1. Deletes prefetch marker from alpha_cache
 * 2. Calls ensureHistoricalPrefetch() to re-fetch all tickers
 *
 * Usage: Can be called manually to refresh cached stock data
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
