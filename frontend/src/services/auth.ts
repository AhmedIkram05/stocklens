/**
 * auth.ts
 *
 * Authentication service for the StockLens FastAPI backend.
 *
 * Replaces the previous Firebase-based authService with JWT token management
 * backed by the backend's /auth/* endpoints.
 *
 * Token storage uses expo-secure-store. Token refresh is handled transparently
 * by the api.ts client (see 401 → refresh → retry logic).
 */

import { apiService, ApiAuthError } from './api';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SignUpRequest {
  fullName: string;
  email: string;
  password: string;
}

export interface SignInRequest {
  email: string;
  password: string;
}

/** Shape returned by GET /auth/me and embedded in AuthResponse. */
export interface UserProfile {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/** Shape returned by POST /auth/register and POST /auth/login. */
export interface AuthResponse {
  user: UserProfile;
  tokens: TokenPair;
}

export interface MessageResponse {
  message: string;
}

// ── Service ───────────────────────────────────────────────────────────────────

export const authService = {
  /**
   * Register a new user.
   *
   * Tokens are automatically persisted to SecureStore on success.
   */
  async signUp(data: SignUpRequest): Promise<AuthResponse> {
    const response = await apiService.post<AuthResponse>(
      '/auth/register',
      {
        email: data.email,
        password: data.password,
        full_name: data.fullName,
      },
      { skipAuth: true },
    );

    // Persist tokens
    await apiService.setTokens(response.tokens.access_token, response.tokens.refresh_token);
    return response;
  },

  /**
   * Authenticate an existing user.
   *
   * Tokens are automatically persisted to SecureStore on success.
   */
  async signIn(data: SignInRequest): Promise<AuthResponse> {
    const response = await apiService.post<AuthResponse>('/auth/login', {
      email: data.email,
      password: data.password,
    });

    // Persist tokens
    await apiService.setTokens(response.tokens.access_token, response.tokens.refresh_token);
    return response;
  },

  /**
   * Sign out the current user.
   *
   * Sends the refresh token to the server for server-side revocation, then
   * clears both tokens from SecureStore regardless of the server response.
   */
  async signOut(): Promise<void> {
    try {
      const refreshToken = await apiService.getRefreshToken();
      await apiService.post<void>('/auth/logout', {
        refresh_token: refreshToken,
      });
    } catch {
      // Tolerate network/server errors — local token cleanup is the priority.
    }
    await apiService.clearTokens();
  },

  /**
   * Fetch the current user's profile from GET /auth/me.
   *
   * Returns `null` when the session is expired or invalid (no error thrown).
   */
  async getProfile(): Promise<UserProfile | null> {
    try {
      return await apiService.get<UserProfile>('/auth/me');
    } catch (error) {
      if (error instanceof ApiAuthError) {
        return null;
      }
      throw error;
    }
  },

  /**
   * Check whether the user has a valid (non-expired) session.
   *
   * If the access token is expired, attempts a silent refresh before returning.
   */
  async isAuthenticated(): Promise<boolean> {
    const token = await apiService.getAccessToken();
    if (!token) return false;

    // Check token presence + profile fetch to validate server-side
    try {
      const profile = await this.getProfile();
      return profile !== null;
    } catch {
      return false;
    }
  },

  /**
   * Request a password reset email.
   *
   * Always succeeds from the caller's perspective to avoid revealing whether
   * the email exists in the system. Returns a user-facing message.
   */
  async forgotPassword(email: string): Promise<MessageResponse> {
    return apiService.post<MessageResponse>('/auth/forgot-password', { email });
  },
};

// Re-export the UserProfile type for consumers that need it.
export type { UserProfile as AuthUserProfile };

// Backward-compatible aliases for screens migrating from Firebase.
// These are handled by AuthContext's mapping layer — no direct import needed.
