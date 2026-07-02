/**
 * DeviceAuthPrompt
 *
 * Prompt helper to enable device passcode/biometric login and store credentials.
 */

import { Alert } from 'react-native';
import * as deviceAuth from '../hooks/useDeviceAuth';

/** Prompt the user to enable device auth and save credentials on acceptance. */
export async function promptEnableDeviceAuth(email: string, password: string): Promise<boolean> {
  try {
    const available = await deviceAuth.isDeviceAuthAvailable();
    if (!available) return false;

    return new Promise<boolean>((resolve) => {
      Alert.alert(
        'Enable Device Auth?',
        'Use your device passcode or biometrics to sign in faster and securely. Enable now?',
        [
          {
            text: 'No',
            style: 'cancel',
            onPress: async () => {
              try {
                await deviceAuth.clearDeviceCredentials();
              } catch (err) {}
              resolve(false);
            },
          },
          {
            text: 'Yes',
            onPress: async () => {
              try {
                await deviceAuth.saveDeviceCredentials(email, password);
                Alert.alert(
                  'Enabled',
                  'Device passcode login enabled. You can now unlock the app with your device credentials.',
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
