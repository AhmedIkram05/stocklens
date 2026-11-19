/** Device auth utilities (biometrics/passcode helpers). */

import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';

const DEVICE_ENABLED_KEY = 'device_enabled';
// Legacy key from when the account password was stored on device. Deleted on sight.
const LEGACY_CREDENTIALS_KEY = 'device_credentials';

/** Check whether device authentication (passcode/biometrics) is available. */
export async function isDeviceAuthAvailable(): Promise<boolean> {
  try {
    const level = await LocalAuthentication.getEnrolledLevelAsync();
    // SECRET = passcode-only; BIOMETRIC_* = enrolled biometrics.
    return level !== LocalAuthentication.SecurityLevel.NONE;
  } catch (e) {
    return false;
  }
}

/**
 * Prompt the native device authentication dialog.
 * @param promptMessage - message shown in the dialog
 */
export async function authenticateDevice(
  promptMessage = 'Authenticate',
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await LocalAuthentication.authenticateAsync({
      promptMessage,
      disableDeviceFallback: false,
    });
    if (res.success) return { success: true };
    return { success: false, error: res.error ?? 'Authentication failed, please try again.' };
  } catch (e: any) {
    return { success: false, error: e?.message ?? 'Unknown error' };
  }
}

/** Remove the legacy stored account password, if present. */
export async function clearDeviceCredentials(): Promise<void> {
  await SecureStore.deleteItemAsync(LEGACY_CREDENTIALS_KEY);
}

/** Enable or disable device-auth by setting/clearing the enabled flag. */
export async function setDeviceEnabled(enabled: boolean): Promise<void> {
  if (!enabled) {
    await SecureStore.deleteItemAsync(DEVICE_ENABLED_KEY);
    return;
  }
  await SecureStore.setItemAsync(DEVICE_ENABLED_KEY, '1', {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

/** Return whether device-auth is currently enabled. */
export async function isDeviceEnabled(): Promise<boolean> {
  try {
    const v = await SecureStore.getItemAsync(DEVICE_ENABLED_KEY);
    return !!v;
  } catch (e) {
    return false;
  }
}

export default {
  isDeviceAuthAvailable,
  authenticateDevice,
  clearDeviceCredentials,
  setDeviceEnabled,
  isDeviceEnabled,
};
