/**
 * Integration tests for `AuthContext`.
 * Exercises auth state handling, device-unlock flows, credential checks,
 * and provider usage requirements.
 */

import React from 'react';
import { act, renderHook } from '@testing-library/react-native';
import { AppState, AppStateStatus } from 'react-native';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';

// Mock new auth service and API client to avoid actual HTTP calls during tests
jest.mock('@/services/auth', () => ({
  authService: {
    signIn: jest.fn(),
    signUp: jest.fn(),
    signOut: jest.fn(),
    getProfile: jest.fn(),
    isAuthenticated: jest.fn(),
  },
}));

jest.mock('@/services/api', () => ({
  apiService: {
    getAccessToken: jest.fn(),
    getRefreshToken: jest.fn(),
    setTokens: jest.fn(),
    clearTokens: jest.fn(),
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    upload: jest.fn(),
  },
  ApiError: Error,
  ApiAuthError: Error,
}));

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

  // Mock return values
  beforeEach(() => {
    const { authService } = require('@/services/auth');
    const { apiService } = require('@/services/api');
    apiService.getAccessToken.mockResolvedValue(null);
    authService.signIn.mockResolvedValue({
      user: {
        id: 'test-id-1',
        email: 'demo@example.com',
        display_name: 'TestUser',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      tokens: {
        access_token: 'test-at',
        refresh_token: 'test-rt',
        expires_in: 3600,
      },
    });
    authService.signOut.mockResolvedValue(undefined);
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
  it('unlockWithCredentials verifies credentials via backend API', async () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    await act(async () => {
      const success = await result.current.unlockWithCredentials('demo@example.com', 'password');
      expect(success).toBe(true);
    });
  });

  // ── Additional tests to cover uncovered lines ─────────────────────────—

  /**
   * Test: Initial auth with valid token
   * Lines covered: 139-144
   */
  it('loads user profile when valid token and profile exist', async () => {
    const { authService } = require('@/services/auth');
    const { apiService } = require('@/services/api');

    apiService.getAccessToken.mockResolvedValue('valid-token');
    authService.getProfile.mockResolvedValue({
      id: 'u1',
      email: 'a@b.com',
      display_name: 'Test User',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    expect(result.current.user).toEqual(
      expect.objectContaining({
        id: 'u1',
        email: 'a@b.com',
        display_name: 'Test User',
        uid: 'u1',
        first_name: 'Test User',
      }),
    );
    expect(result.current.loading).toBe(false);
  });

  /**
   * Test: Initial auth with invalid token
   * Lines covered: 147-150
   */
  it('clears tokens when stored token is invalid', async () => {
    const { authService } = require('@/services/auth');
    const { apiService } = require('@/services/api');

    apiService.getAccessToken.mockResolvedValue('bad-token');
    authService.getProfile.mockRejectedValue(new Error('Invalid token'));

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    expect(apiService.clearTokens).toHaveBeenCalled();
    expect(result.current.user).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  /**
   * Test: unlockWithCredentials when signIn returns falsy
   * Line covered: 248
   */
  it('unlockWithCredentials returns false when signIn returns null', async () => {
    const { authService } = require('@/services/auth');
    authService.signIn.mockResolvedValue(null);

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    let success = true;
    await act(async () => {
      success = await result.current.unlockWithCredentials('test@test.com', 'password');
    });

    expect(success).toBe(false);
  });

  /**
   * Test: unlockWithCredentials catch path
   * Lines covered: 249-250
   */
  it('unlockWithCredentials returns false when signIn throws', async () => {
    const { authService } = require('@/services/auth');
    authService.signIn.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    let success = true;
    await act(async () => {
      success = await result.current.unlockWithCredentials('test@test.com', 'password');
    });

    expect(success).toBe(false);
  });

  /**
   * Test: refreshUser with valid profile
   * Lines covered: 257-260
   */
  it('refreshUser sets user when getProfile succeeds', async () => {
    const { authService } = require('@/services/auth');

    authService.getProfile.mockResolvedValue({
      id: 'u1',
      email: 'a@b.com',
      display_name: 'User',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    expect(result.current.user).toBeNull();

    await act(async () => {
      await result.current.refreshUser();
    });

    expect(result.current.user).toEqual(
      expect.objectContaining({
        id: 'u1',
        uid: 'u1',
        first_name: 'User',
      }),
    );
  });

  /**
   * Test: refreshUser with null profile
   * Lines covered: 263-264
   */
  it('refreshUser clears tokens when getProfile returns null', async () => {
    const { authService } = require('@/services/auth');
    const { apiService } = require('@/services/api');

    authService.getProfile.mockResolvedValue(null);

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    expect(result.current.user).toBeNull();

    await act(async () => {
      await result.current.refreshUser();
    });

    expect(apiService.clearTokens).toHaveBeenCalled();
    expect(result.current.user).toBeNull();
  });

  /**
   * Test: signOutUser catch path
   * Lines covered: 291-292
   */
  it('signOutUser clears state even when signOut throws', async () => {
    const { authService } = require('@/services/auth');
    authService.signOut.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    await act(async () => {
      await result.current.signOutUser();
    });

    expect(result.current.user).toBeNull();
    expect(result.current.locked).toBe(false);
  });

  /**
   * Test: startLockGrace called multiple times
   * Line covered: 300
   */
  it('startLockGrace can be called multiple times without error', async () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    expect(() => {
      act(() => {
        result.current.startLockGrace();
        result.current.startLockGrace();
      });
    }).not.toThrow();

    expect(result.current.locked).toBe(false);
  });

  /**
   * Test: unlockWithDeviceAuth failure path
   * Line covered: 224
   */
  it('unlockWithDeviceAuth returns false when device auth does not succeed', async () => {
    const { authenticateDevice } = require('@/hooks/useDeviceAuth');
    authenticateDevice.mockResolvedValue({ success: false });

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    let success = true;
    await act(async () => {
      success = await result.current.unlockWithDeviceAuth();
    });

    expect(success).toBe(false);
  });

  /**
   * Test: unlockWithDeviceAuth catch path
   * Line covered: 226
   */
  it('unlockWithDeviceAuth returns false when authenticateDevice throws', async () => {
    const { authenticateDevice } = require('@/hooks/useDeviceAuth');
    authenticateDevice.mockRejectedValue(new Error('Device auth error'));

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    let success = true;
    await act(async () => {
      success = await result.current.unlockWithDeviceAuth();
    });

    expect(success).toBe(false);
  });

  /**
   * Test: signOutUser clears grace timer
   * Lines covered: 276-277
   */
  it('signOutUser clears grace timer when grace period is active', async () => {
    const { authService } = require('@/services/auth');
    authService.signOut.mockResolvedValue(undefined);

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
    });

    await act(async () => {});

    act(() => {
      result.current.startLockGrace();
    });

    await act(async () => {
      await result.current.signOutUser();
    });

    expect(result.current.user).toBeNull();
    expect(result.current.locked).toBe(false);
  });

  // ── AppState lock behaviour tests ───────────────────────────────────—

  describe('AppState lock behaviour', () => {
    let simulateAppState: (state: AppStateStatus) => void;

    beforeEach(() => {
      let currentAppState: AppStateStatus = 'active';
      const handlers: Function[] = [];

      jest.spyOn(AppState, 'addEventListener').mockImplementation((_event: any, handler: any) => {
        handlers.push(handler);
        return {
          remove: () => {
            const idx = handlers.indexOf(handler);
            if (idx !== -1) handlers.splice(idx, 1);
          },
        };
      });

      Object.defineProperty(AppState, 'currentState', {
        get: () => currentAppState,
        configurable: true,
      });

      simulateAppState = (state: AppStateStatus) => {
        currentAppState = state;
        handlers.forEach((h) => h(state));
      };
    });

    afterEach(() => {
      jest.restoreAllMocks();
      Object.defineProperty(AppState, 'currentState', {
        value: 'active',
        configurable: true,
        writable: true,
      });
    });

    /**
     * Test: Background lock with active user
     * Lines covered: 166-182
     */
    it('locks app after delay when app backgrounds with active user', async () => {
      const { authService } = require('@/services/auth');
      const { apiService } = require('@/services/api');

      apiService.getAccessToken.mockResolvedValue('valid-token');
      authService.getProfile.mockResolvedValue({
        id: 'u1',
        email: 'a@b.com',
        display_name: 'User',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
      });

      await act(async () => {});

      expect(result.current.user).not.toBeNull();

      await act(async () => {
        simulateAppState('background');
      });

      // Not locked yet — delay timer pending
      expect(result.current.locked).toBe(false);

      // Fast-forward past the lock delay
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(result.current.locked).toBe(true);
    });

    /**
     * Test: Foreground cancels pending lock
     * Lines covered: 186-197
     */
    it('cancels pending lock when app returns to foreground before delay expires', async () => {
      const { authService } = require('@/services/auth');
      const { apiService } = require('@/services/api');

      apiService.getAccessToken.mockResolvedValue('valid-token');
      authService.getProfile.mockResolvedValue({
        id: 'u1',
        email: 'a@b.com',
        display_name: 'User',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
      });

      await act(async () => {});

      expect(result.current.user).not.toBeNull();

      // Background → timer starts
      await act(async () => {
        simulateAppState('background');
      });

      expect(result.current.locked).toBe(false);

      // Return to foreground before 5s delay expires
      await act(async () => {
        simulateAppState('active');
      });

      // Advance past the delay — should not lock since timer was cancelled
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(result.current.locked).toBe(false);
    });

    /**
     * Test: signOutUser clears delay timer
     * Lines covered: 281-282
     */
    it('clears lock delay timer on signOut when app is backgrounded', async () => {
      const { authService } = require('@/services/auth');
      const { apiService } = require('@/services/api');

      apiService.getAccessToken.mockResolvedValue('valid-token');
      authService.getProfile.mockResolvedValue({
        id: 'u1',
        email: 'a@b.com',
        display_name: 'User',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
      });

      await act(async () => {});

      // Background → delay timer starts
      await act(async () => {
        simulateAppState('background');
      });

      // signOutUser clears the delay timer
      await act(async () => {
        await result.current.signOutUser();
      });

      expect(result.current.user).toBeNull();
      expect(result.current.locked).toBe(false);
    });

    /**
     * Test: unlockWithDeviceAuth clears pending lock timer
     * Lines covered: 218-219
     */
    it('unlockWithDeviceAuth clears pending lock timer', async () => {
      const { authService } = require('@/services/auth');
      const { apiService } = require('@/services/api');
      const { authenticateDevice } = require('@/hooks/useDeviceAuth');

      apiService.getAccessToken.mockResolvedValue('valid-token');
      authService.getProfile.mockResolvedValue({
        id: 'u1',
        email: 'a@b.com',
        display_name: 'User',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      authenticateDevice.mockResolvedValue({ success: true });

      const { result } = renderHook(() => useAuth(), {
        wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
      });

      await act(async () => {});

      // Background → delay timer starts
      await act(async () => {
        simulateAppState('background');
      });

      expect(result.current.locked).toBe(false);

      // Unlock with device auth — clears the pending delay timer
      await act(async () => {
        await result.current.unlockWithDeviceAuth();
      });

      // Advance past the original delay — should not lock (timer was cleared)
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(result.current.locked).toBe(false);
    });

    /**
     * Test: unlockWithCredentials clears pending lock timer
     * Lines covered: 242-243
     */
    it('unlockWithCredentials clears pending lock timer', async () => {
      const { authService } = require('@/services/auth');
      const { apiService } = require('@/services/api');

      apiService.getAccessToken.mockResolvedValue('valid-token');
      authService.getProfile.mockResolvedValue({
        id: 'u1',
        email: 'a@b.com',
        display_name: 'User',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
      });

      await act(async () => {});

      // Background → delay timer starts
      await act(async () => {
        simulateAppState('background');
      });

      expect(result.current.locked).toBe(false);

      // Unlock with credentials — clears the pending delay timer
      await act(async () => {
        await result.current.unlockWithCredentials('demo@example.com', 'password');
      });

      // Advance past the original delay — should not lock (timer was cleared)
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      expect(result.current.locked).toBe(false);
    });
  });
});
