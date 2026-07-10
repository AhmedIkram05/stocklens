/**
 * api.ts
 *
 * HTTP client for the StockLens FastAPI backend with automatic JWT refresh.
 *
 * Features:
 * - Bearer token injection from SecureStore
 * - Auto-refresh on 401 responses (deduplicated to prevent race conditions)
 * - Singleton refresh promise to avoid concurrent refresh calls
 * - Typed convenience methods (get, post, put, delete, upload)
 * - Error types for auth vs generic errors
 */

import * as SecureStore from 'expo-secure-store';

const ACCESS_TOKEN_KEY = 'stocklens_access_token';
const REFRESH_TOKEN_KEY = 'stocklens_refresh_token';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

// ── JWT helpers ───────────────────────────────────────────────────────────────

/**
 * Decode a JWT payload without verifying the signature.
 * Relies on the backend to issue well-formed tokens.
 */
function decodeJWT(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

/** Returns true when the token's `exp` claim is in the past (with 10s buffer). */
function isTokenExpired(token: string): boolean {
  const payload = decodeJWT(token);
  if (!payload || typeof payload.exp !== 'number') return true;
  return Date.now() >= (payload.exp - 10) * 1000;
}

// ── Refresh logic (singleton) ─────────────────────────────────────────────────

/**
 * In-flight refresh promise.
 *
 * Multiple concurrent requests that encounter a 401 will all await the same
 * promise, ensuring only one refresh call reaches the server.
 */
let refreshPromise: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  try {
    const refreshToken = await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
    if (!refreshToken) return false;

    const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      // Server rejected the refresh — clear everything
      await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
      await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
      return false;
    }

    const data = await response.json();
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, data.access_token);
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

// ── Error types ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class ApiAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ApiAuthError';
  }
}

// ── Fetch wrapper ─────────────────────────────────────────────────────────────

export interface ApiOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  /** Skip Bearer-token injection. Used for public endpoints like login/register. */
  skipAuth?: boolean;
}

/**
 * Parse an error response into a human-readable message.
 * Handles FastAPI's `{detail: ...}` and generic JSON error shapes.
 */
async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') return body.detail;
    if (typeof body.message === 'string') return body.message;
    return JSON.stringify(body);
  } catch {
    // Non-JSON error body (e.g. plain-text 500). Surface the raw text so the
    // user never sees a generic "Unknown error".
    try {
      const text = await response.text();
      return text || response.statusText || 'Unknown error';
    } catch {
      return response.statusText || 'Unknown error';
    }
  }
}

/**
 * Core HTTP request function.
 *
 * - Injects `Authorization: Bearer <token>` unless `skipAuth` is true.
 * - Automatically refreshes the access token when a 401 is received (once per
 *   failed request), then retries the original request.
 * - Deduplicates concurrent refresh calls via a singleton promise.
 *
 * @param endpoint  Path starting with `/` (e.g. `/auth/me`).
 * @param options   Request configuration.
 * @returns         Parsed JSON response body.
 */
export async function api<T = unknown>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = 'GET', headers = {}, body, skipAuth = false } = options;

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  };

  // ── Token injection & pre-emptive refresh ──
  if (!skipAuth) {
    let accessToken = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);

    if (accessToken && isTokenExpired(accessToken)) {
      // Deduplicate concurrent refresh attempts
      if (!refreshPromise) {
        refreshPromise = refreshTokens();
      }
      const refreshed = await refreshPromise;
      refreshPromise = null;

      if (refreshed) {
        accessToken = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
      } else {
        throw new ApiAuthError('Session expired');
      }
    }

    if (accessToken) {
      requestHeaders['Authorization'] = `Bearer ${accessToken}`;
    }
  }

  // ── Initial request ──
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method,
    headers: requestHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });

  // ── 401 → refresh → retry ──
  if (response.status === 401 && !skipAuth) {
    if (!refreshPromise) {
      refreshPromise = refreshTokens();
    }
    const refreshed = await refreshPromise;
    refreshPromise = null;

    if (refreshed) {
      const newToken = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
      requestHeaders['Authorization'] = `Bearer ${newToken}`;

      const retryResponse = await fetch(`${API_BASE_URL}${endpoint}`, {
        method,
        headers: requestHeaders,
        body: body ? JSON.stringify(body) : undefined,
      });

      if (!retryResponse.ok) {
        const msg = await parseError(retryResponse);
        throw new ApiError(retryResponse.status, msg);
      }

      return retryResponse.status === 204 ? (undefined as unknown as T) : retryResponse.json();
    }

    throw new ApiAuthError('Session expired');
  }

  // ── Error handling ──
  if (!response.ok) {
    const msg = await parseError(response);
    throw new ApiError(response.status, msg);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json();
}

// ── Convenience methods ───────────────────────────────────────────────────────

export const apiService = {
  get: <T = unknown>(endpoint: string, options?: ApiOptions) =>
    api<T>(endpoint, { ...options, method: 'GET' }),

  post: <T = unknown>(endpoint: string, body?: unknown, options?: ApiOptions) =>
    api<T>(endpoint, { ...options, method: 'POST', body }),

  put: <T = unknown>(endpoint: string, body?: unknown, options?: ApiOptions) =>
    api<T>(endpoint, { ...options, method: 'PUT', body }),

  delete: <T = unknown>(endpoint: string, options?: ApiOptions) =>
    api<T>(endpoint, { ...options, method: 'DELETE' }),

  /**
   * Upload a file via multipart/form-data.
   * Content-Type is omitted so fetch sets the correct boundary automatically.
   * Bypasses api() to avoid JSON.stringify on FormData.
   */
  upload: async <T = unknown>(
    endpoint: string,
    formData: FormData,
    options?: ApiOptions,
  ): Promise<T> => {
    const headers: Record<string, string> = { ...options?.headers };
    // Let fetch set Content-Type with the correct boundary
    delete headers['Content-Type'];

    // Inject auth token (same logic as api())
    if (!options?.skipAuth) {
      let accessToken = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
      if (accessToken && isTokenExpired(accessToken)) {
        if (!refreshPromise) refreshPromise = refreshTokens();
        const refreshed = await refreshPromise;
        refreshPromise = null;
        if (refreshed) {
          accessToken = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
        } else {
          throw new ApiAuthError('Session expired');
        }
      }
      if (accessToken) {
        headers['Authorization'] = `Bearer ${accessToken}`;
      }
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'POST',
      headers,
      body: formData,
    });

    // ── 401 → refresh → retry (mirrors api()) ──
    if (response.status === 401 && !options?.skipAuth) {
      if (!refreshPromise) {
        refreshPromise = refreshTokens();
      }
      const refreshed = await refreshPromise;
      refreshPromise = null;

      if (refreshed) {
        const newToken = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
        headers['Authorization'] = `Bearer ${newToken}`;

        const retryResponse = await fetch(`${API_BASE_URL}${endpoint}`, {
          method: 'POST',
          headers,
          body: formData,
        });

        if (!retryResponse.ok) {
          const msg = await parseError(retryResponse);
          throw new ApiError(retryResponse.status, msg);
        }

        return retryResponse.status === 204 ? (undefined as unknown as T) : retryResponse.json();
      }

      throw new ApiAuthError('Session expired');
    }

    if (!response.ok) {
      const msg = await parseError(response);
      throw new ApiError(response.status, msg);
    }

    return response.status === 204 ? (undefined as unknown as T) : response.json();
  },

  // ── Token management ──

  getAccessToken: () => SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
  getRefreshToken: () => SecureStore.getItemAsync(REFRESH_TOKEN_KEY),

  setTokens: async (accessToken: string, refreshToken: string) => {
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken);
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken);
  },

  clearTokens: async () => {
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  },
};
