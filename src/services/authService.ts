/**
 * AuthService
 *
 * Firebase authentication helpers for sign-up, sign-in and password reset.
 */

import type { UserCredential } from 'firebase/auth';

/**
 * SignUpData type - User registration data
 *
 * @property firstName - User's first name
 * @property email - Email address (used for login)
 * @property password - Password (min 6 chars per Firebase default)
 */
export interface SignUpData {
  firstName: string;
  email: string;
  password: string;
}

/**
 * SignInData type - User login credentials
 *
 * @property email - Email address
 * @property password - Password
 */
export interface SignInData {
  email: string;
  password: string;
}

/** Firebase auth helper methods. */
export const authService = {
  /** Create a new user account and sync local profile. */
  async signUp({ firstName, email, password }: SignUpData): Promise<UserCredential> {
    try {
      const { getAuthInstance } = await import('./firebase');
      const { createUserWithEmailAndPassword, updateProfile } = await import('firebase/auth');
      const { userService } = await import('./dataService');

      const auth = await getAuthInstance();
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);

      await updateProfile(userCredential.user, {
        displayName: firstName,
      });

      await userService.upsert(userCredential.user.uid, firstName, email);

      return userCredential;
    } catch (error) {
      throw error;
    }
  },

  /** Authenticate existing user and update local profile. */
  async signIn({ email, password }: SignInData): Promise<UserCredential> {
    try {
      const { getAuthInstance } = await import('./firebase');
      const { signInWithEmailAndPassword } = await import('firebase/auth');
      const { userService } = await import('./dataService');

      const auth = await getAuthInstance();
      const userCredential = await signInWithEmailAndPassword(auth, email, password);

      await userService.upsert(
        userCredential.user.uid,
        userCredential.user.displayName || null,
        email,
      );

      return userCredential;
    } catch (error) {
      throw error;
    }
  },

  /** Send a password reset email to the given address. */
  async sendPasswordReset(email: string): Promise<void> {
    try {
      const { getAuthInstance } = await import('./firebase');
      const { sendPasswordResetEmail } = await import('firebase/auth');
      const auth = await getAuthInstance();
      await sendPasswordResetEmail(auth, email);
    } catch (error) {
      throw error;
    }
  },

  /** Fetch user profile from local database by UID. */
  async getUserData(userId: string) {
    try {
      const { userService } = await import('./dataService');
      return await userService.getByUid(userId);
    } catch (error) {
      throw error;
    }
  },
};
