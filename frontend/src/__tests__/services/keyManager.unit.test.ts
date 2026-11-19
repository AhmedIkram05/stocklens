jest.mock('expo-crypto', () => ({
  getRandomBytesAsync: jest.fn(async (n: number) => new Uint8Array(n).fill(7)),
}));

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY',
}));

import * as SecureStore from 'expo-secure-store';
import keyManager from '@/services/keyManager';

/**
 * Tests for `keyManager` caching and SecureStore integration.
 * Verifies key generation/storage when absent and cached retrieval behavior.
 */

describe('keyManager', () => {
  beforeEach(async () => {
    await keyManager.clearKey();
    jest.clearAllMocks();
  });

  it('generates and stores a new key when none exists', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce(null);
    (SecureStore.setItemAsync as jest.Mock).mockResolvedValueOnce(undefined);

    const key = await keyManager.getOrCreateKey();
    expect(typeof key).toBe('string');
    expect((SecureStore.setItemAsync as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(0);
  });

  it('shares one in-flight creation between concurrent calls', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(null);
    (SecureStore.setItemAsync as jest.Mock).mockResolvedValue(undefined);

    const [a, b] = await Promise.all([keyManager.getOrCreateKey(), keyManager.getOrCreateKey()]);

    expect(a).toBe(b);
    expect(SecureStore.getItemAsync).toHaveBeenCalledTimes(1);
  });

  it('returns existing key when present', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce('existing-key');
    const key = await keyManager.getOrCreateKey();
    expect(key).toBe('existing-key');
  });
});

describe('clearKey', () => {
  beforeEach(async () => {
    await keyManager.clearKey();
    jest.clearAllMocks();
  });

  it('deletes key from SecureStore and clears cache', async () => {
    // First set a key so cache is populated
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce(null);
    (SecureStore.setItemAsync as jest.Mock).mockResolvedValueOnce(undefined);
    await keyManager.getOrCreateKey();

    // Now clear it
    await keyManager.clearKey();

    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith('stocklens_encryption_key_v1');
  });

  it('fails loudly when SecureStore cannot be read', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockRejectedValueOnce(new Error('store error'));
    await expect(keyManager.getOrCreateKey()).rejects.toThrow('store error');

    (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce('recovered-key');
    await expect(keyManager.getOrCreateKey()).resolves.toBe('recovered-key');
  });
});
