import * as Crypto from 'expo-crypto';

jest.mock('expo-crypto', () => ({
  getRandomBytesAsync: jest.fn(async (n: number) => new Uint8Array(n).fill(3)),
}));

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
  const key = await generateKeyBase64();
  expect(Crypto.getRandomBytesAsync).toHaveBeenCalledWith(32);
  const plain = 'hello test';
  const cipher = await encryptString(plain, key);
  expect(Crypto.getRandomBytesAsync).toHaveBeenCalledWith(12);
  expect(isEncryptedPayload(cipher)).toBe(true);
  const dec = await decryptString(cipher, key);
  expect(dec).toBe(plain);
});
