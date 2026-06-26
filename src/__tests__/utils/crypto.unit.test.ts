import {
  generateKeyBase64,
  encryptString,
  decryptString,
  isEncryptedPayload,
} from '@/utils/crypto';

/**
 * Tests for `crypto` helpers.
 * Verifies AES-GCM encrypt/decrypt roundtrip and encrypted-payload detection.
 */

test('crypto roundtrip and detection', async () => {
  const key = generateKeyBase64();
  const plain = 'hello test';
  const cipher = await encryptString(plain, key);
  expect(isEncryptedPayload(cipher)).toBe(true);
  const dec = await decryptString(cipher, key);
  expect(dec).toBe(plain);
});
