/**
 * Tests for device authentication helpers (`useDeviceAuth`).
 * Validates hardware checks, authentication flow, credential storage,
 * and enable/disable flag behavior.
 */

import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';
import {
  isDeviceAuthAvailable,
  authenticateDevice,
  saveDeviceCredentials,
  getDeviceCredentials,
  clearDeviceCredentials,
  setDeviceEnabled,
  isDeviceEnabled,
} from '@/hooks/useDeviceAuth';

jest.mock('expo-local-authentication', () => ({
  hasHardwareAsync: jest.fn(),
  authenticateAsync: jest.fn(),
  supportedAuthenticationTypesAsync: jest.fn(),
}));

jest.mock('expo-secure-store', () => ({
  setItemAsync: jest.fn(),
  getItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
  ALWAYS_THIS_DEVICE_ONLY: 'ALWAYS_THIS_DEVICE_ONLY',
}));

const mockedLocalAuth = LocalAuthentication as jest.Mocked<typeof LocalAuthentication>;
const mockedSecureStore = SecureStore as jest.Mocked<typeof SecureStore>;

describe('useDeviceAuth', () => {
  // Ensure a clean mock state before each test
  beforeEach(() => {
    jest.clearAllMocks();
  });

  /**
   * isDeviceAuthAvailable
   * - Verifies detection logic for device authentication hardware.
   * - Tests both positive and negative hardware combinations.
   */
  describe('isDeviceAuthAvailable', () => {
    it('returns true when hardware exists', async () => {
      mockedLocalAuth.hasHardwareAsync.mockResolvedValue(true);

      const result = await isDeviceAuthAvailable();

      expect(result).toBe(true);
    });

    it('returns false when hardware missing', async () => {
      mockedLocalAuth.hasHardwareAsync.mockResolvedValue(false);

      const result = await isDeviceAuthAvailable();

      expect(result).toBe(false);
    });
  });

  /**
   * authenticateDevice
   * - Simulates user device authentication and verifies returned results
   *   and the arguments passed into the native API wrapper.
   */
  describe('authenticateDevice', () => {
    it('returns success when authentication succeeds', async () => {
      mockedLocalAuth.authenticateAsync.mockResolvedValue({ success: true } as any);

      const result = await authenticateDevice('Test prompt');

      expect(result.success).toBe(true);
      expect(mockedLocalAuth.authenticateAsync).toHaveBeenCalledWith({
        promptMessage: 'Test prompt',
        disableDeviceFallback: false,
      });
    });

    it('returns failure when authentication fails', async () => {
      mockedLocalAuth.authenticateAsync.mockResolvedValue({
        success: false,
        error: 'User canceled',
      } as any);

      const result = await authenticateDevice();

      expect(result.success).toBe(false);
      expect(result.error).toBe('User canceled');
    });
  });

  /**
   * Credential storage helpers
   * - Ensures credentials are securely saved/retrieved via SecureStore
   * - Ensures clearing credentials also removes the enabled flag
   */
  describe('credential storage', () => {
    it('saves and retrieves credentials securely', async () => {
      await saveDeviceCredentials('user@example.com', 'pass123');

      // Verify SecureStore called with serialized credentials and proper options
      expect(mockedSecureStore.setItemAsync).toHaveBeenCalledWith(
        'device_credentials',
        JSON.stringify({ email: 'user@example.com', password: 'pass123' }),
        { keychainAccessible: SecureStore.ALWAYS_THIS_DEVICE_ONLY },
      );

      // Simulate stored value and verify retrieval parsing
      mockedSecureStore.getItemAsync.mockResolvedValue(
        JSON.stringify({ email: 'user@example.com', password: 'pass123' }),
      );

      const result = await getDeviceCredentials();

      expect(result).toEqual({ email: 'user@example.com', password: 'pass123' });
    });

    it('clears credentials and disables device auth', async () => {
      await clearDeviceCredentials();

      expect(mockedSecureStore.deleteItemAsync).toHaveBeenCalledWith('device_credentials');
      expect(mockedSecureStore.deleteItemAsync).toHaveBeenCalledWith('device_enabled');
    });
  });

  /**
   * Enabled flag helpers
   * - Tests saving and reading the device auth enabled flag
   */
  describe('enabled state', () => {
    it('manages device auth enabled flag', async () => {
      await setDeviceEnabled(true);
      expect(mockedSecureStore.setItemAsync).toHaveBeenCalledWith(
        'device_enabled',
        '1',
        expect.any(Object),
      );

      mockedSecureStore.getItemAsync.mockResolvedValue('1');
      const result = await isDeviceEnabled();
      expect(result).toBe(true);
    });
  });
});
