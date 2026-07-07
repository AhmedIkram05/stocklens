/**
 * AuthContext
 *
 * Provides authentication state and unlock/lock helpers via React context.
 *
 * Replaced Firebase Auth with the StockLens FastAPI backend (JWT-based).
 * Token lifecycle:
 *   1. On mount: check SecureStore for access token, validate via GET /auth/me
 *   2. On sign-in/sign-up: POST /auth/login or /auth/register, persist tokens
 *   3. On sign-out: POST /auth/logout, clear SecureStore
 *   4. Token refresh: handled transparently by the api.ts HTTP client
 *
 * Device-lock (Face ID / Touch ID) behaviour is preserved unchanged.
 */

import React, { createContext, useContext, useEffect, useState, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { useTheme } from './ThemeContext';
import { authService } from '@/services/auth';
import { apiService } from '@/services/api';
import type { UserProfile as AuthUserProfile } from '@/services/auth';
import { authenticateDevice, isDeviceAuthAvailable, isDeviceEnabled } from '@/hooks/useDeviceAuth';

// ── Backward-compatible profile type ──────────────────────────────────────────
// Screens still reference `uid` (aliased to `id`) and `first_name` (aliased to
// `display_name`).  The mapping layer in `_buildProfile` provides these.

export interface UserProfile extends AuthUserProfile {
  /** Backward-compatible alias for `id` (used by screens and hooks). */
  uid: string;
  /** Backward-compatible alias for `display_name`. */
  first_name: string | null;
}

export interface AuthContextType {
  /** Authenticated user profile (null when not authenticated). */
  user: UserProfile | null;
  /** Same reference as `user` — retained for backward compatibility. */
  userProfile: UserProfile | null;
  /** True during the initial auth-state check on mount. */
  loading: boolean;
  /** Signs out and clears all persisted tokens. */
  signOutUser: () => Promise<void>;
  /** True when the device lock is active (app backgrounded). */
  locked: boolean;
  /** Attempts to unlock using Face ID / Touch ID. */
  unlockWithDeviceAuth: () => Promise<boolean>;
  /** Unlocks using email + password credentials. */
  unlockWithCredentials: (email: string, password: string) => Promise<boolean>;
  /** Starts a 10-second grace period to prevent immediate re-lock after auth. */
  startLockGrace: () => void;
  /** Re-fetches the user profile from the backend using stored tokens and updates state. */
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * useAuth Hook
 *
 * Access authentication state from any component.  Throws if used outside of
 * an {@link AuthProvider}.
 *
 * @example
 * const { user, locked, unlockWithDeviceAuth } = useAuth();
 */
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: React.ReactNode;
}

// ── Mapping helper ────────────────────────────────────────────────────────────

/**
 * Enrich a raw API profile with backward-compatible fields.
 *
 * The database stores `display_name`; older screen code expects `uid` (→ `id`)
 * and `first_name` (→ `display_name`).
 */
function _buildProfile(raw: AuthUserProfile): UserProfile {
  return {
    ...raw,
    uid: raw.id,
    first_name: raw.display_name,
  };
}

// ── Provider ──────────────────────────────────────────────────────────────────

/**
 * AuthProvider Component
 *
 * Lifecycle:
 * 1. **Mount** – Checks SecureStore for existing tokens.  If found, calls
 *    `GET /auth/me` to validate the session and populate the user profile.
 * 2. **Auth change** – Login / register triggers a token fetch via
 *    {@link authService}, which persists tokens and returns the profile.
 * 3. **Background / foreground** – The device-lock gate activates when the app
 *    backgrounds for >5 s (configurable) and requires Face ID / passcode to
 *    resume.
 * 4. **Unmount** – Cleans up subscriptions and timers.
 *
 * Lock Logic (unchanged from Firebase version):
 * - `LOCK_ENABLED` flag controls whether the lock feature is active.
 * - `lockGraceActive` ref prevents immediate lock for 10 s after sign-in.
 * - `lockDelayTimer` defers lock activation by 5 s after backgrounding.
 */
export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const appState = useRef<AppStateStatus | null>(null);
  const [locked, setLocked] = useState(false);
  const LOCK_ENABLED = true;
  const lockGraceActive = useRef(false);
  const lockGraceTimer = useRef<NodeJS.Timeout | null>(null);
  const lockDelayTimer = useRef<NodeJS.Timeout | null>(null);
  const LOCK_DELAY_MS = 5000;
  const { setMode } = useTheme();

  // ── Initial auth check on mount ────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const initAuth = async () => {
      try {
        const token = await apiService.getAccessToken();
        if (!token) {
          if (!cancelled) setLoading(false);
          return;
        }

        const profile = await authService.getProfile();
        if (!cancelled) {
          if (profile) {
            setUser(_buildProfile(profile));
          }
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          // Token present but invalid — clear silently
          await apiService.clearTokens();
          setLoading(false);
        }
      }
    };

    initAuth();

    return () => {
      cancelled = true;
    };
  }, []);

  // ── App-state listener (device lock on background) ─────────────────────────
  useEffect(() => {
    appState.current = AppState.currentState;
    const handle = (nextAppState: AppStateStatus) => {
      const wasActive = !!(appState.current && appState.current.match(/active/));
      const isBackgrounding = !!nextAppState.match(/inactive|background/);

      // Active → background: start delayed lock
      if (wasActive && isBackgrounding) {
        if (LOCK_ENABLED && user && !lockGraceActive.current) {
          if (lockDelayTimer.current) {
            clearTimeout(lockDelayTimer.current);
          }
          lockDelayTimer.current = setTimeout(() => {
            const current = AppState.currentState;
            if (current.match(/inactive|background/) && !lockGraceActive.current) {
              setLocked(true);
            }
            lockDelayTimer.current = null;
          }, LOCK_DELAY_MS);
        }
      }

      // Background → active: cancel delayed lock
      if (
        appState.current &&
        appState.current.match(/inactive|background/) &&
        nextAppState.match(/active/)
      ) {
        if (lockDelayTimer.current) {
          clearTimeout(lockDelayTimer.current);
          lockDelayTimer.current = null;
        }
      }

      appState.current = nextAppState;
    };

    const sub = AppState.addEventListener('change', handle);
    return () => sub.remove();
  }, [user]);

  // ── Unlock helpers ─────────────────────────────────────────────────────────

  const unlockWithDeviceAuth = async (): Promise<boolean> => {
    try {
      if (!LOCK_ENABLED) {
        setLocked(false);
        return true;
      }
      const available = await isDeviceAuthAvailable();
      const enabled = await isDeviceEnabled();
      if (!available || !enabled) return false;
      const { success } = await authenticateDevice('Unlock StockLens');
      if (success) {
        if (lockDelayTimer.current) {
          clearTimeout(lockDelayTimer.current);
          lockDelayTimer.current = null;
        }
        startLockGrace();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  };

  const unlockWithCredentials = async (email: string, password: string): Promise<boolean> => {
    try {
      if (!LOCK_ENABLED) {
        setLocked(false);
        return true;
      }

      // Validate credentials against the backend
      const result = await authService.signIn({ email, password });
      if (result) {
        setUser(_buildProfile(result.user));
        if (lockDelayTimer.current) {
          clearTimeout(lockDelayTimer.current);
          lockDelayTimer.current = null;
        }
        startLockGrace();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  };

  // ── Refresh user from stored tokens ────────────────────────────────────────

  const refreshUser = async (): Promise<void> => {
    try {
      const profile = await authService.getProfile();
      if (profile) {
        setUser(_buildProfile(profile));
      } else {
        // Token present but invalid — clear
        await apiService.clearTokens();
        setUser(null);
      }
    } catch {
      // Network error — leave current state unchanged
    }
  };

  // ── Sign out ───────────────────────────────────────────────────────────────

  const signOutUser = async () => {
    try {
      if (lockGraceTimer.current) {
        clearTimeout(lockGraceTimer.current);
        lockGraceTimer.current = null;
      }
      lockGraceActive.current = false;
      if (lockDelayTimer.current) {
        clearTimeout(lockDelayTimer.current);
        lockDelayTimer.current = null;
      }

      await authService.signOut();
      setUser(null);
      setLocked(false);
      setMode('light');
    } catch {
      // Ensure local state is cleared even if the server call fails
      setUser(null);
      setLocked(false);
    }
  };

  // ── Lock grace period ──────────────────────────────────────────────────────

  const startLockGrace = () => {
    if (lockGraceTimer.current) {
      clearTimeout(lockGraceTimer.current);
    }
    lockGraceActive.current = true;
    setLocked(false);

    lockGraceTimer.current = setTimeout(() => {
      lockGraceActive.current = false;
      lockGraceTimer.current = null;
    }, 10000);
  };

  // ── Context value ──────────────────────────────────────────────────────────

  const value: AuthContextType = {
    user,
    userProfile: user,
    loading,
    signOutUser,
    locked,
    unlockWithDeviceAuth,
    unlockWithCredentials,
    startLockGrace,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
