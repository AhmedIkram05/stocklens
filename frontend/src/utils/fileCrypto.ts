import * as FileSystem from 'expo-file-system/legacy';
import keyManager from '@/services/keyManager';
import crypto, { isEncryptedPayload } from '@/utils/crypto';

/**
 * fileCrypto
 *
 * Decrypt helper for encrypted image files (decrypt to a temp file).
 */
// Use any-cast to avoid TypeScript surface-level mismatch with expo-file-system
const FS: any = FileSystem as any;

// Lightweight UUIDv4 generator (avoid importing 'uuid' to keep Jest/node happy)
function generateUuidV4() {
  // from https://stackoverflow.com/a/2117523/404792
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Decrypt an encrypted .enc image to a temporary cache file, or return input if not encrypted. */
export async function decryptImageToTemp(encUri: string): Promise<string> {
  // Plain local images are never encrypted — skip the whole-file read for them.
  if (!encUri || !encUri.toLowerCase().endsWith('.enc')) return encUri;
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

export default { decryptImageToTemp };
