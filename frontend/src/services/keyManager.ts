/**
 * KeyManager
 *
 * Generate and retrieve the app-wide AES-256 key stored in secure storage.
 */
import * as SecureStore from 'expo-secure-store';
import { generateKeyBase64 } from '@/utils/crypto';

const KEY_NAME = 'stocklens_encryption_key_v1';

let keyPromise: Promise<string> | null = null;

/**
 * getOrCreateKey
 *
 * Retrieves the base64-encoded AES key from SecureStore or generates a new
 * one if none exists. The key is generated with a secure RNG and encoded as
 * base64 for storage. The function guarantees a non-null string result.
 *
 * @returns Promise<string> - base64 encoded 32-byte AES key
 */
export function getOrCreateKey(): Promise<string> {
  if (keyPromise) return keyPromise;

  const pending = (async () => {
    const stored = await SecureStore.getItemAsync(KEY_NAME);
    if (stored) return stored;

    const newKey = await generateKeyBase64();
    await SecureStore.setItemAsync(KEY_NAME, newKey, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
    return newKey;
  })();
  const guarded = pending.catch((error) => {
    if (keyPromise === guarded) keyPromise = null;
    throw error;
  });
  keyPromise = guarded;
  return guarded;
}

/**
 * clearKey
 *
 * Removes the stored encryption key from SecureStore. Use with caution — once
 * removed, previously encrypted data cannot be decrypted unless a backup exists.
 */
export async function clearKey(): Promise<void> {
  keyPromise = null;
  await SecureStore.deleteItemAsync(KEY_NAME);
}

export default { getOrCreateKey, clearKey };
