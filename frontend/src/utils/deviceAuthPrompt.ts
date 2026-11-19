/**
 * DeviceAuthPrompt
 *
 * Prompt helper to enable device passcode/biometric unlock. No account
 * credentials are stored on the device.
 */

import { Alert } from 'react-native';
import * as deviceAuth from '../hooks/useDeviceAuth';

/** Prompt the user to enable device auth. */
export async function promptEnableDeviceAuth(): Promise<boolean> {
  try {
    // Remove any password stored by older builds before doing anything else.
    await deviceAuth.clearDeviceCredentials().catch(() => {});
    const available = await deviceAuth.isDeviceAuthAvailable();
    if (!available) return false;

    return new Promise<boolean>((resolve) => {
      Alert.alert(
        'Enable Device Auth?',
        'Use your device passcode or biometrics to unlock the app. Enable now?',
        [
          {
            text: 'No',
            style: 'cancel',
            onPress: async () => {
              await deviceAuth.setDeviceEnabled(false).catch(() => {});
              resolve(false);
            },
          },
          {
            text: 'Yes',
            onPress: async () => {
              try {
                await deviceAuth.setDeviceEnabled(true);
                Alert.alert(
                  'Enabled',
                  'Device passcode unlock enabled. No password is stored on this device.',
                );
                resolve(true);
              } catch (err) {
                resolve(false);
              }
            },
          },
        ],
        { cancelable: true },
      );
    });
  } catch (e) {
    return false;
  }
}

export default promptEnableDeviceAuth;
