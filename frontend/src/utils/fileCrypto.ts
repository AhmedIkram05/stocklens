import * as FileSystem from 'expo-file-system/legacy';
import keyManager from '@/services/keyManager';
import crypto, { isEncryptedPayload } from '@/utils/crypto';

/**
 * fileCrypto
 *
 * Encrypt/decrypt helpers for image files (encrypt to .enc, decrypt to temp file).
 */
// Use any-cast to avoid TypeScript surface-level mismatch with expo-file-system
const FS: any = FileSystem as any;
const ENCRYPTED_DIR = `${FS.documentDirectory}encrypted_images/`;

// Lightweight UUIDv4 generator (avoid importing 'uuid' to keep Jest/node happy)
function generateUuidV4() {
  // from https://stackoverflow.com/a/2117523/404792
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Ensure encrypted images directory exists. */
async function ensureDir() {
  try {
    await FS.makeDirectoryAsync(ENCRYPTED_DIR, { intermediates: true });
  } catch (e) {}
}

/** Encrypt an image file and return encrypted .enc URI (falls back to original on error). */
export async function encryptImageFile(origUri: string): Promise<string> {
  if (!origUri) return origUri;
  await ensureDir();
  try {
    // read as base64
    const b64 = await FS.readAsStringAsync(origUri, { encoding: 'base64' });
    const key = await keyManager.getOrCreateKey();
    const payload = await crypto.encryptString(b64, key);
    const dest = `${ENCRYPTED_DIR}${generateUuidV4()}.enc`;
    await FS.writeAsStringAsync(dest, payload, { encoding: 'utf8' });
    return dest;
  } catch (e) {
    // on failure, fall back to original URI
    return origUri;
  }
}

/** Decrypt an encrypted .enc image to a temporary cache file, or return input if not encrypted. */
export async function decryptImageToTemp(encUri: string): Promise<string> {
  if (!encUri) return encUri;
  try {
    const payload = await FS.readAsStringAsync(encUri, { encoding: 'utf8' });
    if (!isEncryptedPayload(payload)) return encUri; // not encrypted
    const key = await keyManager.getOrCreateKey();
    const b64 = await crypto.decryptString(payload, key);
    const tmp = `${FS.cacheDirectory}dec-${generateUuidV4()}.jpg`;
    await FS.writeAsStringAsync(tmp, b64, { encoding: 'base64' });
    return tmp;
  } catch (e) {
    return encUri;
  }
}

export default { encryptImageFile, decryptImageToTemp };
