/**
 * Integration tests for `AuthContext`.
 * Exercises auth state handling, device-unlock flows, credential checks,
 * and provider usage requirements.
 */

import React from 'react';
import { act, renderHook } from '@testing-library/react-native';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';

// Mock Firebase auth module to avoid actual authentication calls during tests
jest.mock('@/services/firebase', () => ({
  getAuthInstance: jest.fn(async () => ({ currentUser: null })),
}));

jest.mock('firebase/auth', () => {
  const { act } = require('@testing-library/react-native');
  return {
    onAuthStateChanged: jest.fn((_auth, callback) => {
      act(() => {
        callback(null);
      });
      return jest.fn();
    }),
    signOut: jest.fn(async () => {}),
    signInWithEmailAndPassword: jest.fn(async () => ({ user: { uid: 'uid-1' } })),
  };
});

jest.mock('@/services/dataService', () => {
  const { createUserProfile } = require('../fixtures');
  return {
    userService: {
      getByUid: jest.fn(async () => createUserProfile({ uid: 'uid-1', email: 'demo@example.com' })),
      upsert: jest.fn(async () => 1),
    },
  };
});

jest.mock('@/hooks/useDeviceAuth', () => ({
  isDeviceAuthAvailable: jest.fn(async () => true),
  isDeviceEnabled: jest.fn(async () => true),
  authenticateDevice: jest.fn(async () => ({ success: true })),
  saveDeviceCredentials: jest.fn(),
  getDeviceCredentials: jest.fn(),
  clearDeviceCredentials: jest.fn(),
  setDeviceEnabled: jest.fn(),
}));

jest.mock('@/contexts/ThemeContext', () => {
  const actual = jest.requireActual('@/contexts/ThemeContext');
  return {
    ...actual,
    useTheme: () => ({ setMode: jest.fn() }),
  };
});

describe('AuthContext', () => {
  // Setup: Clear mocks and use fake timers for async operations
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  // Cleanup: Restore real timers after each test
  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  /**
   * Test: Context provider requirement
   * Validates that useAuth hook throws error when used outside AuthProvider.
   * This prevents undefined behavior and helps developers catch mistakes early.
   */
  it('throws when useAuth is used outside provider', () => {
    expect(() =>
      renderHook(() => useAuth(), { wrapper: ({ children }) => <>{children}</> }),
    ).toThrow('useAuth must be used within an AuthProvider');
  });

  /**
   * Test: Device unlock flow
   * Validates that app unlocks when native device authentication succeeds.
   * Critical for security feature - ensures users can access locked app with their device credentials.
   */
  it('provides unlocked state when device auth succeeds', async () => {
    // Render the auth hook with provider
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {}); // Wait for initial auth state

    // Trigger device-auth unlock
    await act(async () => {
      await result.current.unlockWithDeviceAuth();
    });

    // Verify app is now unlocked
    expect(result.current.locked).toBe(false);
  });

  /**
   * Test: Sign-out flow
   * Validates that signing out resets the lock state to unlocked.
   * Ensures clean state after logout - user shouldn't see lock screen without being signed in.
   */
  it('signs out and resets lock state', async () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {}); // Wait for initial state

    // Trigger sign-out
    await act(async () => {
      await result.current.signOutUser();
    });

    // Verify lock state is reset (unlocked)
    expect(result.current.locked).toBe(false);
  });

  /**
   * Test: Credential-based unlock
   * Validates that users can unlock app by entering email/password.
   * Fallback mechanism when device authentication fails or isn't available.
   */
  it('unlockWithCredentials verifies credentials via Firebase', async () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    await act(async () => {
      const success = await result.current.unlockWithCredentials('demo@example.com', 'password');
      expect(success).toBe(true);
    });
  });
});
