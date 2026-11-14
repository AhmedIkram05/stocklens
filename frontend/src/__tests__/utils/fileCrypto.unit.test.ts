// Mock the filesystem and crypto/keyManager dependencies
jest.mock('expo-file-system/legacy', () => ({
  readAsStringAsync: jest.fn(),
  writeAsStringAsync: jest.fn(),
  documentDirectory: '/tmp/doc/',
  cacheDirectory: '/tmp/cache/',
}));

jest.mock('@/services/keyManager', () => ({ getOrCreateKey: jest.fn(async () => 'test-key') }));
jest.mock('@/utils/crypto', () => ({
  decryptString: jest.fn(async (s: string) =>
    typeof s === 'string' && s.startsWith('enc:') ? s.slice(4) : s,
  ),
  isEncryptedPayload: jest.fn((s: any) => typeof s === 'string' && s.startsWith('enc:')),
}));

import * as FS from 'expo-file-system/legacy';
import fileCrypto from '@/utils/fileCrypto';

/**
 * Tests for `fileCrypto` helpers.
 * Verifies decrypt-to-temp behavior using mocked FS.
 */

describe('fileCrypto', () => {
  beforeEach(() => jest.clearAllMocks());

  it('decrypts an encrypted .enc file to a tmp path', async () => {
    (FS.readAsStringAsync as jest.Mock).mockResolvedValueOnce('enc:BASE64');
    (FS.writeAsStringAsync as jest.Mock).mockResolvedValueOnce(undefined);

    const tmp = await fileCrypto.decryptImageToTemp('/tmp/doc/enc-1.enc');
    expect(typeof tmp).toBe('string');
    expect((FS.writeAsStringAsync as jest.Mock).mock.calls.length).toBeGreaterThan(0);
  });

  it('returns plain (non-.enc) images without reading the file', async () => {
    const out = await fileCrypto.decryptImageToTemp('/tmp/doc/photo.jpg');
    expect(out).toBe('/tmp/doc/photo.jpg');
    expect(FS.readAsStringAsync).not.toHaveBeenCalled();
  });
});
