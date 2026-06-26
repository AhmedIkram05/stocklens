/**
 * FirebaseService
 *
 * Firebase app and auth initialization with optional SQLite persistence.
 */

import { Platform } from 'react-native';
import { initializeApp, getApps, getApp, FirebaseApp } from 'firebase/app';
import type { Auth, Persistence } from 'firebase/auth';
import db from './database';
import { firebaseConfig } from './firebaseConfig';
import keyManager from './keyManager';
import { encryptString, decryptString, isEncryptedPayload } from '@/utils/crypto';

/**
 * Firebase app instance (singleton)
 */
let app: FirebaseApp | null = null;

/**
 * Firebase auth instance (singleton)
 */
let authInstance: Auth | null = null;

/**
 * SQLite table name for auth state persistence
 */
const AUTH_STATE_TABLE = 'auth_state';

/**
 * Track whether auth_state table has been created
 */
let authTableInitialized = false;

/**
 * Storage availability check key (used to test SQLite write/delete)
 */
const STORAGE_AVAILABLE_KEY = '__sak';

/**
 * PersistenceValue type - Auth state data structure
 */
type PersistenceValue = string | Record<string, unknown>;

/**
 * Ensure auth_state table exists in SQLite
 *
 * Creates table if not exists, idempotent (safe to call multiple times)
 */
async function ensureAuthTable() {
  if (authTableInitialized) {
    return;
  }
  await db.execAsync(
    `CREATE TABLE IF NOT EXISTS ${AUTH_STATE_TABLE} (
      key TEXT PRIMARY KEY,
      value TEXT
    );`,
  );
  authTableInitialized = true;
}

/**
 * Create custom SQLite persistence for Firebase Auth
 *
 * @returns Firebase Persistence implementation using SQLite
 *
 * Features:
 * - Implements Firebase Persistence interface (_get, _set, _remove, _isAvailable)
 * - Stores auth tokens and state in auth_state table
 * - Type: 'LOCAL' (persists across app restarts)
 * - Automatic table creation on first use
 *
 * Methods:
 * - _isAvailable: Tests SQLite write/delete to verify storage works
 * - _set: Persists key-value pair as JSON in SQLite
 * - _get: Retrieves and parses JSON from SQLite
 * - _remove: Deletes key from SQLite
 * - _addListener/_removeListener: No-op (not needed for SQLite)
 *
 * Integration:
 * Used by initializeAuth() on iOS/Android platforms
 */
function createSQLitePersistence(): Persistence {
  return class SQLitePersistence {
    static type: 'LOCAL' = 'LOCAL';
    readonly type = 'LOCAL' as const;

    async _isAvailable(): Promise<boolean> {
      try {
        await ensureAuthTable();
        await db.runAsync(`INSERT OR REPLACE INTO ${AUTH_STATE_TABLE} (key, value) VALUES (?, ?)`, [
          STORAGE_AVAILABLE_KEY,
          '1',
        ]);
        await db.runAsync(`DELETE FROM ${AUTH_STATE_TABLE} WHERE key = ?`, [STORAGE_AVAILABLE_KEY]);
        return true;
      } catch (error) {
        return false;
      }
    }

    async _set(key: string, value: PersistenceValue): Promise<void> {
      await ensureAuthTable();
      // Store encrypted JSON payload where possible to protect auth tokens/state
      let payload: string = JSON.stringify(value);
      try {
        const k = await keyManager.getOrCreateKey();
        payload = await encryptString(payload, k);
      } catch (e) {
        // fallback to plaintext JSON
      }
      await db.runAsync(`INSERT OR REPLACE INTO ${AUTH_STATE_TABLE} (key, value) VALUES (?, ?)`, [
        key,
        payload,
      ]);
    }

    async _get<T extends PersistenceValue>(key: string): Promise<T | null> {
      await ensureAuthTable();
      const rows = (await db.getAllAsync(`SELECT value FROM ${AUTH_STATE_TABLE} WHERE key = ?`, [
        key,
      ])) as Array<{ value: string | null }>;
      if (rows.length === 0 || rows[0].value == null) {
        return null;
      }
      const raw = rows[0].value as string;
      // Attempt decryption if payload looks encrypted, otherwise parse JSON as before
      try {
        const k = await keyManager.getOrCreateKey();
        if (isEncryptedPayload(raw)) {
          try {
            const dec = await decryptString(raw, k);
            return JSON.parse(dec) as T;
          } catch (e) {
            // decryption failed, fall through to parse attempt
          }
        }
        try {
          return JSON.parse(raw) as T;
        } catch {
          return raw as unknown as T;
        }
      } catch (e) {
        // If key retrieval failed, try to parse raw stored value
        try {
          return JSON.parse(raw) as T;
        } catch {
          return raw as unknown as T;
        }
      }
    }

    async _remove(key: string): Promise<void> {
      await ensureAuthTable();
      await db.runAsync(`DELETE FROM ${AUTH_STATE_TABLE} WHERE key = ?`, [key]);
    }

    _addListener(_key: string, _listener: (value: PersistenceValue | null) => void): void {}

    _removeListener(_key: string, _listener: (value: PersistenceValue | null) => void): void {}
  } as unknown as Persistence;
}

/**
 * Initialize Firebase app (idempotent)
 *
 * @returns Firebase app instance
 *
 * Features:
 * - Singleton pattern (only initializes once)
 * - Uses firebaseConfig from firebaseConfig.ts
 * - Safe to call multiple times (returns existing instance)
 */
function initializeFirebaseIfNeeded() {
  if (!app) {
    if (getApps().length === 0) {
      app = initializeApp(firebaseConfig);
    } else {
      app = getApp();
    }
  }
  return app;
}

/**
 * Get Firebase Auth instance with platform-specific persistence
 *
 * @returns Promise<Auth> - Firebase Auth instance
 *
 * Platform Behavior:
 * - iOS/Android: Uses custom SQLite persistence (auth_state table)
 * - Web: Uses browser local storage (fallback to in-memory)
 *
 * Features:
 * - Lazy initialization (only creates auth when first called)
 * - Singleton pattern (returns same instance on subsequent calls)
 * - Dynamic imports for code splitting
 * - Automatic persistence setup
 *
 * Integration:
 * Called by authService for all authentication operations
 */
export async function getAuthInstance(): Promise<Auth> {
  if (!authInstance) {
    const firebaseApp = initializeFirebaseIfNeeded();
    if (Platform.OS === 'ios' || Platform.OS === 'android') {
      const { initializeAuth } = await import('firebase/auth');
      const persistence = createSQLitePersistence();
      authInstance = initializeAuth(firebaseApp, { persistence });
    } else {
      const { getAuth, browserLocalPersistence, inMemoryPersistence, setPersistence } =
        await import('firebase/auth');
      const webAuth = getAuth(firebaseApp);
      try {
        await setPersistence(webAuth, browserLocalPersistence);
      } catch {
        await setPersistence(webAuth, inMemoryPersistence);
      }
      authInstance = webAuth;
    }
  }
  return authInstance!;
}

export default app;
