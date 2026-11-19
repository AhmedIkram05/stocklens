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
  clearDeviceCredentials,
  setDeviceEnabled,
  isDeviceEnabled,
} from '@/hooks/useDeviceAuth';

jest.mock('expo-local-authentication', () => ({
  hasHardwareAsync: jest.fn(),
  getEnrolledLevelAsync: jest.fn(),
  authenticateAsync: jest.fn(),
  SecurityLevel: { NONE: 0, SECRET: 1, BIOMETRIC_WEAK: 2, BIOMETRIC_STRONG: 3 },
}));

jest.mock('expo-secure-store', () => ({
  setItemAsync: jest.fn(),
  getItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY',
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
    it('returns true for a passcode-only device', async () => {
      mockedLocalAuth.hasHardwareAsync.mockResolvedValue(true);
      mockedLocalAuth.getEnrolledLevelAsync.mockResolvedValue(1 as any);

      const result = await isDeviceAuthAvailable();

      expect(result).toBe(true);
    });

    it('returns false when nothing is enrolled', async () => {
      mockedLocalAuth.hasHardwareAsync.mockResolvedValue(true);
      mockedLocalAuth.getEnrolledLevelAsync.mockResolvedValue(0 as any);

      const result = await isDeviceAuthAvailable();

      expect(result).toBe(false);
    });

    it('returns false when the level check throws', async () => {
      mockedLocalAuth.getEnrolledLevelAsync.mockRejectedValue(new Error('denied'));

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

    it('returns failure when authentication throws', async () => {
      mockedLocalAuth.authenticateAsync.mockRejectedValue(new Error('biometrics unavailable'));

      const result = await authenticateDevice();

      expect(result.success).toBe(false);
      expect(result.error).toBe('biometrics unavailable');
    });
  });

  describe('legacy credential cleanup', () => {
    it('deletes the legacy stored password key', async () => {
      await clearDeviceCredentials();
      expect(mockedSecureStore.deleteItemAsync).toHaveBeenCalledWith('device_credentials');
    });

    it('disables device auth by deleting the enabled flag', async () => {
      await setDeviceEnabled(false);
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

    it('returns false when isDeviceEnabled check throws', async () => {
      mockedSecureStore.getItemAsync.mockRejectedValue(new Error('locked'));

      const result = await isDeviceEnabled();

      expect(result).toBe(false);
    });
  });
});
