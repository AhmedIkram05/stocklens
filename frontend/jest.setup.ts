/**
 * JestSetup
 *
 * Test environment setup for Jest: enables `fetch` mocking, provides
 * environment variables and lightweight native/Expo mocks for deterministic tests.
 */

import React from 'react';
import '@testing-library/jest-native/extend-expect';
import 'jest-fetch-mock';

// ponytail: jest-fetch-mock promises resolve on microtasks that escape React's
// act() scope after render. Suppressing the act() warning is accepted practice
// for integration tests when async effects (fetch, timers) are tested implicitly
// through waitFor assertions.
const origError = console.error;
console.error = (...args: any[]) => {
  if (typeof args[0] === 'string' && args[0].includes('inside a test was not wrapped in act')) {
    return;
  }
  origError.call(console, ...args);
};

const fetchMock = require('jest-fetch-mock');

fetchMock.enableMocks();

process.env.EXPO_PUBLIC_API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

jest.mock('expo-constants', () => ({
  manifest: { extra: {} },
  expoConfig: { extra: {} },
}));

jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn(),
  ImpactFeedbackStyle: {
    Light: 'light',
    Medium: 'medium',
    Heavy: 'heavy',
  },
}));

jest.mock('expo-status-bar', () => ({
  StatusBar: () => null,
}));

jest.mock('expo-blur', () => ({
  BlurView: ({ children }: { children?: React.ReactNode }) => children ?? null,
}));

jest.mock('expo-linear-gradient', () => ({
  LinearGradient: ({ children }: { children?: React.ReactNode }) => children ?? null,
}));

jest.mock('expo-camera', () => ({
  CameraView: jest.fn(() => null),
  CameraType: {
    back: 'back',
    front: 'front',
  },
  useCameraPermissions: jest.fn(() => [{ status: 'granted', granted: true }, jest.fn()]),
  requestCameraPermissionsAsync: jest.fn(async () => ({ granted: true, status: 'granted' })),
}));

jest.mock('expo-local-authentication', () => ({
  authenticateAsync: jest.fn(async () => ({ success: true })),
  hasHardwareAsync: jest.fn(async () => true),
  isEnrolledAsync: jest.fn(async () => true),
  supportedAuthenticationTypesAsync: jest.fn(async () => []),
}));

jest.mock('expo-secure-store', () => {
  const secureStoreData = new Map<string, string>();

  return {
    setItemAsync: jest.fn(async (key: string, value: string) => {
      secureStoreData.set(key, value);
    }),
    getItemAsync: jest.fn(async (key: string) => secureStoreData.get(key) ?? null),
    deleteItemAsync: jest.fn(async (key: string) => {
      secureStoreData.delete(key);
    }),
  };
});

jest.mock('expo-sqlite', () => {
  const executeSql = jest.fn(
    (statement: string, _params: unknown[] = [], success?: Function, error?: Function) => {
      if (success) {
        success({
          rows: { _array: [], length: 0 },
          rowsAffected: 0,
          insertId: undefined,
        });
      }

      if (error) {
        error(null);
      }
    },
  );

  const transaction = jest.fn((callback: (tx: { executeSql: typeof executeSql }) => void) => {
    const tx = { executeSql };
    callback(tx);
  });

  const mockDb = {
    transaction,
    exec: jest.fn(),
    runAsync: jest.fn(),
    getAllAsync: jest.fn().mockResolvedValue([]),
  };

  return {
    openDatabase: jest.fn(() => mockDb),
    openDatabaseSync: jest.fn(() => mockDb),
  };
});

try {
  require.resolve('react-native-reanimated/mock');
  jest.mock('react-native-reanimated', () => require('react-native-reanimated/mock'));
} catch (error) {
  jest.mock(
    'react-native-reanimated',
    () => ({
      __esModule: true,
      default: {},
      View: 'View',
      ScrollView: 'ScrollView',
      createAnimatedComponent: (component: unknown) => component,
      useSharedValue: () => ({ value: 0 }),
      useAnimatedStyle: () => ({}),
      useAnimatedProps: () => ({}),
      withTiming: (value: number) => value,
      Easing: { cubic: jest.fn() },
    }),
    { virtual: true },
  );
}

jest.mock('@expo/vector-icons', () => {
  const React = require('react');
  return {
    Ionicons: ({ children, ...props }: any) => React.createElement('Icon', props, children ?? null),
  };
});

const RN = require('react-native');
if (RN?.AppState) {
  RN.AppState.currentState = 'active';
  RN.AppState.addEventListener = jest.fn(() => ({ remove: jest.fn() }));
  RN.AppState.removeEventListener = jest.fn();
}

// ponytail: keep failure output short — don't dump the full component tree
// on query errors; the assertion message is enough to diagnose.
const RTL = require('@testing-library/react-native');
if (RTL?.configure) {
  RTL.configure({
    getElementError: (message: string | null) => new Error(message ?? 'Unable to find an element.'),
  });
}
