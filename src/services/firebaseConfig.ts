/**
 * FirebaseConfig
 *
 * Loads and validates Firebase configuration from environment/expo-constants.
 */

import Constants from 'expo-constants';

/**
 * Firebase configuration object
 *
 * Loaded from environment variables via expo-constants or process.env
 */
const firebaseConfig = {
  apiKey: Constants.expoConfig?.extra?.EXPO_PUBLIC_API_KEY || process.env.EXPO_PUBLIC_API_KEY,
  authDomain:
    Constants.expoConfig?.extra?.EXPO_PUBLIC_AUTH_DOMAIN || process.env.EXPO_PUBLIC_AUTH_DOMAIN,
  projectId:
    Constants.expoConfig?.extra?.EXPO_PUBLIC_PROJECT_ID || process.env.EXPO_PUBLIC_PROJECT_ID,
  storageBucket:
    Constants.expoConfig?.extra?.EXPO_PUBLIC_STORAGE_BUCKET ||
    process.env.EXPO_PUBLIC_STORAGE_BUCKET,
  messagingSenderId:
    Constants.expoConfig?.extra?.EXPO_PUBLIC_MESSAGING_SENDER_ID ||
    process.env.EXPO_PUBLIC_MESSAGING_SENDER_ID,
  appId: Constants.expoConfig?.extra?.EXPO_PUBLIC_APP_ID || process.env.EXPO_PUBLIC_APP_ID,
  measurementId:
    Constants.expoConfig?.extra?.EXPO_PUBLIC_MEASUREMENT_ID ||
    process.env.EXPO_PUBLIC_MEASUREMENT_ID,
};

/**
 * Required Firebase config keys (must be present)
 */
const requiredKeys = [
  'apiKey',
  'authDomain',
  'projectId',
  'storageBucket',
  'messagingSenderId',
  'appId',
];

/**
 * Validate Firebase config on module load
 *
 * Throws error if any required keys are missing
 * Prevents app from starting with incomplete Firebase configuration
 */
const missingKeys = requiredKeys.filter(
  (key) => !firebaseConfig[key as keyof typeof firebaseConfig],
);

if (missingKeys.length > 0) {
  throw new Error(
    `Firebase configuration is incomplete. Missing environment variables: ${missingKeys.join(', ')}. ` +
      'Please check your .env file and ensure all EXPO_PUBLIC_FIREBASE_* variables are set.',
  );
}

export { firebaseConfig };
