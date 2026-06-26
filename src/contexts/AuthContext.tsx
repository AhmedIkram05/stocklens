/**
 * AuthContext
 *
 * Provides authentication state and unlock/lock helpers via React context.
 */

import React, { createContext, useContext, useEffect, useState, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { useTheme } from './ThemeContext';
import type { User } from 'firebase/auth';
import { onAuthStateChanged, signInWithEmailAndPassword, signOut } from 'firebase/auth';
import { getAuthInstance } from '@/services/firebase';
import { userService } from '@/services/dataService';
import { authenticateDevice, isDeviceAuthAvailable, isDeviceEnabled } from '@/hooks/useDeviceAuth';

export interface UserProfile {
  id?: number;
  uid: string;
  first_name?: string | null;
  email: string;
  created_at?: string;
  last_login?: string;
}

export interface AuthContextType {
  /** Firebase Auth user object (null if not authenticated) */
  user: User | null;
  /** User profile data from Firestore */
  userProfile: UserProfile | null;
  /** True during initial authentication check */
  loading: boolean;
  /** Signs out the current user and clears auth state */
  signOutUser: () => Promise<void>;
  /** True when the device lock is active (app backgrounded) */
  locked: boolean;
  /** Attempts to unlock using Face ID/Touch ID */
  unlockWithDeviceAuth: () => Promise<boolean>;
  /** Unlocks using email/password credentials from secure storage */
  unlockWithCredentials: (email: string, password: string) => Promise<boolean>;
  /** Starts 10-second grace period to prevent immediate locking after sign-in */
  startLockGrace: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * useAuth Hook
 *
 * Custom hook to access AuthContext from any component.
 * Throws error if used outside AuthProvider to catch integration mistakes early.
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

/**
 * AuthProvider Component
 *
 * Wraps the app to provide authentication state via context.
 * Manages Firebase Auth lifecycle, user profile sync, and lock/unlock behavior.
 *
 * Lifecycle:
 * 1. On mount: Sets up Firebase onAuthStateChanged listener
 * 2. When user signs in: Fetches/creates Firestore profile, loads theme preference
 * 3. When app backgrounds: Sets locked=true (if device lock enabled)
 * 4. When app foregrounds: Requires unlock before access
 * 5. On unmount: Cleans up Firebase listener and AppState subscription
 *
 * Lock Logic:
 * - LOCK_ENABLED flag controls whether lock feature is active
 * - lockGraceActive ref prevents immediate lock for 10s after sign-in
 */
export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const appState = useRef<AppStateStatus | null>(null);
  const [locked, setLocked] = useState(false);
  const LOCK_ENABLED = true;
  const lockGraceActive = useRef(false);
  const lockGraceTimer = useRef<NodeJS.Timeout | null>(null);
  // Timer used to delay locking when the app backgrounds. The app will only
  // become `locked` if it's been backgrounded for more than `LOCK_DELAY_MS`.
  const lockDelayTimer = useRef<NodeJS.Timeout | null>(null);
  const LOCK_DELAY_MS = 5000; // 5 seconds
  const { setMode } = useTheme();

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;

    const initAuth = async () => {
      try {
        await new Promise((resolve) => setTimeout(resolve, 100));
        const auth = await getAuthInstance();

        unsubscribe = onAuthStateChanged(auth, async (usr) => {
          setUser(usr);
          if (usr) {
            try {
              const profile = await userService.getByUid(usr.uid);
              if (!profile) {
                await userService.upsert(usr.uid, usr.displayName || null, usr.email || '');
                setUserProfile(await userService.getByUid(usr.uid));
              } else {
                setUserProfile(profile);
              }
            } catch (err) {}
          } else {
            setUserProfile(null);
          }
          setLoading(false);
        });
      } catch (error) {
        setLoading(false);
      }
    };

    initAuth();

    return () => {
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, []);

  useEffect(() => {
    appState.current = AppState.currentState;
    const handle = (nextAppState: AppStateStatus) => {
      const wasActive = !!(appState.current && appState.current.match(/active/));
      const isBackgrounding = !!nextAppState.match(/inactive|background/);

      // App is transitioning from active -> background/inactive: start delayed lock
      if (wasActive && isBackgrounding) {
        if (LOCK_ENABLED && user && !lockGraceActive.current) {
          // Clear any existing delayed timer
          if (lockDelayTimer.current) {
            clearTimeout(lockDelayTimer.current);
          }
          lockDelayTimer.current = setTimeout(() => {
            // Only lock if still backgrounded and grace not active
            const current = AppState.currentState;
            if (current.match(/inactive|background/) && !lockGraceActive.current) {
              setLocked(true);
            }
            lockDelayTimer.current = null;
          }, LOCK_DELAY_MS);
        }
      }

      // App is transitioning from background/inactive -> active: cancel delayed lock
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
        // Start grace period to prevent immediate re-locking
        // Clear any pending delayed lock and start grace
        if (lockDelayTimer.current) {
          clearTimeout(lockDelayTimer.current);
          lockDelayTimer.current = null;
        }
        startLockGrace();
        return true;
      }
      return false;
    } catch (err) {
      return false;
    }
  };

  const unlockWithCredentials = async (email: string, password: string): Promise<boolean> => {
    try {
      if (!LOCK_ENABLED) {
        setLocked(false);
        return true;
      }

      // Validate credentials without triggering full sign-in
      const auth = await getAuthInstance();

      // Just verify credentials are correct
      await signInWithEmailAndPassword(auth, email, password);

      // If we get here, credentials are valid - start grace period
      if (lockDelayTimer.current) {
        clearTimeout(lockDelayTimer.current);
        lockDelayTimer.current = null;
      }
      startLockGrace();
      return true;
    } catch (err) {
      return false;
    }
  };

  const signOutUser = async () => {
    try {
      // Clear grace period timer if active
      if (lockGraceTimer.current) {
        clearTimeout(lockGraceTimer.current);
        lockGraceTimer.current = null;
      }
      lockGraceActive.current = false;
      // Clear delayed lock timer as well
      if (lockDelayTimer.current) {
        clearTimeout(lockDelayTimer.current);
        lockDelayTimer.current = null;
      }

      const auth = await getAuthInstance();
      await signOut(auth);
      setUserProfile(null);
      setLocked(false);

      // Reset theme to light mode on sign out
      setMode('light');
    } catch (error) {
      throw error;
    }
  };

  /**
   * Starts a 10-second grace period where the lock screen will not trigger.
   * This prevents immediate locking after sign-in/unlock, allowing smooth onboarding.
   * Should be called after successful login, signup, or unlock.
   */
  const startLockGrace = () => {
    // Clear any existing timer
    if (lockGraceTimer.current) {
      clearTimeout(lockGraceTimer.current);
    }

    // Set grace period active and unlock
    lockGraceActive.current = true;
    setLocked(false);

    // Clear grace period after 10 seconds
    lockGraceTimer.current = setTimeout(() => {
      lockGraceActive.current = false;
      lockGraceTimer.current = null;
    }, 10000);
  };

  const value: AuthContextType = {
    user,
    userProfile,
    loading,
    signOutUser,
    locked,
    unlockWithDeviceAuth,
    unlockWithCredentials,
    startLockGrace,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
