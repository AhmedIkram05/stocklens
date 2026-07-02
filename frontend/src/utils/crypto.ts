import forge from 'node-forge';

const b64enc = (s: string) => forge.util.encode64(s);
const b64dec = (s: string) => forge.util.decode64(s);

/** Generate a cryptographically secure 256-bit key (base64). */
export function generateKeyBase64(): string {
  return b64enc(forge.random.getBytesSync(32));
}

/** Heuristic check whether a string looks like the AES-GCM JSON payload. */
export function isEncryptedPayload(str: string): boolean {
  if (!str || typeof str !== 'string') return false;
  try {
    const p = JSON.parse(str);
    // Ensure we return a boolean (not the last truthy value which could be a string)
    return !!(
      p &&
      typeof p.iv === 'string' &&
      typeof p.ct === 'string' &&
      typeof p.tag === 'string'
    );
  } catch (e) {
    return false;
  }
}

/** AES-256-GCM encrypt a UTF-8 string; returns JSON with base64 iv/ct/tag. */
export async function encryptString(plain: string, keyBase64: string): Promise<string> {
  const key = b64dec(keyBase64);
  const iv = forge.random.getBytesSync(12);
  const cipher = forge.cipher.createCipher('AES-GCM', key);
  cipher.start({ iv, tagLength: 128 });
  cipher.update(forge.util.createBuffer(plain, 'utf8'));
  cipher.finish();
  const ct = cipher.output.getBytes();
  const tag = cipher.mode.tag.getBytes();
  return JSON.stringify({ iv: b64enc(iv), ct: b64enc(ct), tag: b64enc(tag) });
}

/** Decrypt the AES-GCM JSON payload back to the original UTF-8 string. */
export async function decryptString(payloadJson: string, keyBase64: string): Promise<string> {
  const payload = JSON.parse(payloadJson);
  const key = b64dec(keyBase64);
  const iv = b64dec(payload.iv);
  const ct = b64dec(payload.ct);
  const tag = b64dec(payload.tag);
  const decipher = forge.cipher.createDecipher('AES-GCM', key);
  decipher.start({ iv, tagLength: 128, tag });
  decipher.update(forge.util.createBuffer(ct));
  const ok = decipher.finish();
  if (!ok) throw new Error('Decryption failed');
  return decipher.output.toString('utf8');
}

export default { generateKeyBase64, encryptString, decryptString, isEncryptedPayload };
