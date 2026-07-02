/**
 * KeyManager
 *
 * Generate and retrieve the app-wide AES-256 key stored in secure storage.
 */
import * as SecureStore from 'expo-secure-store';
import { generateKeyBase64 } from '@/utils/crypto';

const KEY_NAME = 'stocklens_encryption_key_v1';

/**
 * getOrCreateKey
 *
 * Retrieves the base64-encoded AES key from SecureStore or generates a new
 * one if none exists. The key is generated with a secure RNG and encoded as
 * base64 for storage. The function guarantees a non-null string result.
 *
 * @returns Promise<string> - base64 encoded 32-byte AES key
 */
export async function getOrCreateKey(): Promise<string> {
  // Prefer the stored key in SecureStore on each call to remain in sync
  // with native storage (tests and other processes may change it). If
  // the stored key is absent, fall back to an in-memory cached key or
  // generate a new one and attempt to persist it.
  try {
    const stored = await SecureStore.getItemAsync(KEY_NAME);
    if (stored) {
      (getOrCreateKey as any)._cachedKey = stored;
      return stored;
    }
  } catch (e) {
    // If reading SecureStore fails, continue and possibly return the in-memory cache
  }

  // Use in-memory cache if available (avoids regenerating a key between calls when SecureStore is unavailable)
  if ((getOrCreateKey as any)._cachedKey) return (getOrCreateKey as any)._cachedKey as string;

  // Generate and attempt to persist
  const newKey = generateKeyBase64();
  try {
    await SecureStore.setItemAsync(KEY_NAME, newKey as string, {
      keychainAccessible: SecureStore.ALWAYS_THIS_DEVICE_ONLY,
    });
  } catch (e) {
    // ignore store errors; continue with in-memory key
  }
  (getOrCreateKey as any)._cachedKey = newKey;
  return newKey;
}

/**
 * clearKey
 *
 * Removes the stored encryption key from SecureStore. Use with caution — once
 * removed, previously encrypted data cannot be decrypted unless a backup exists.
 */
export async function clearKey(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(KEY_NAME);
  } catch (e) {}
  try {
    delete (getOrCreateKey as any)._cachedKey;
  } catch (e) {}
}

export default { getOrCreateKey, clearKey };
