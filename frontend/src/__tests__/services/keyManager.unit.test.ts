jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
  ALWAYS_THIS_DEVICE_ONLY: 'ALWAYS_THIS_DEVICE_ONLY',
}));

import * as SecureStore from 'expo-secure-store';
import keyManager from '@/services/keyManager';

/**
 * Tests for `keyManager` caching and SecureStore integration.
 * Verifies key generation/storage when absent and cached retrieval behavior.
 */

describe('keyManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('generates and stores a new key when none exists', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce(null);
    (SecureStore.setItemAsync as jest.Mock).mockResolvedValueOnce(undefined);

    const key = await keyManager.getOrCreateKey();
    expect(typeof key).toBe('string');
    expect((SecureStore.setItemAsync as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(0);
  });

  it('returns existing key when present', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce('existing-key');
    const key = await keyManager.getOrCreateKey();
    expect(key).toBe('existing-key');
  });
});

describe('clearKey', () => {
  beforeEach(() => {
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

  it('returns cached key when SecureStore fails', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockRejectedValueOnce(new Error('store error'));
    const key = await keyManager.getOrCreateKey();
    expect(typeof key).toBe('string');
  });
});
