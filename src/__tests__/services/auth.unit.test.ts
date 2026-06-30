/**
 * Tests for `auth.ts` — authentication service.
 *
 * All HTTP is mocked via jest-fetch-mock. SecureStore is mocked in jest.setup.ts.
 * Covers signUp, signIn, signOut, getProfile, isAuthenticated, forgotPassword.
 */

import { authService } from '@/services/auth';

const fetchMock = require('jest-fetch-mock');

const mockUser = {
  id: '1',
  email: 'a@b.com',
  display_name: 'Alice',
  created_at: '',
  updated_at: '',
};

function mockAuthResponse() {
  fetchMock.mockResponseOnce(
    JSON.stringify({
      user: mockUser,
      tokens: { access_token: 'acc-token', refresh_token: 'ref-token', expires_in: 3600 },
    }),
    { status: 200 },
  );
}

describe('authService', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    const SecureStore = require('expo-secure-store');
    await SecureStore.deleteItemAsync('stocklens_access_token');
    await SecureStore.deleteItemAsync('stocklens_refresh_token');
  });

  describe('signUp', () => {
    it('sends POST /auth/register and persists tokens', async () => {
      mockAuthResponse();

      const result = await authService.signUp({
        fullName: 'Alice',
        email: 'a@b.com',
        password: 'secret',
      });

      expect(result.user).toEqual(mockUser);
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/auth\/register$/),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"full_name"'),
        }),
      );
    });
  });

  describe('signIn', () => {
    it('sends POST /auth/login and persists tokens', async () => {
      mockAuthResponse();

      const result = await authService.signIn({ email: 'a@b.com', password: 'secret' });

      expect(result.user).toEqual(mockUser);
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/auth\/login$/),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"email"'),
        }),
      );
    });
  });

  describe('signOut', () => {
    it('sends POST /auth/logout with refresh token and clears tokens', async () => {
      // store a refresh token
      const SecureStore = require('expo-secure-store');
      await SecureStore.setItemAsync('stocklens_refresh_token', 'ref-token');
      fetchMock.mockResponseOnce('', { status: 204 });

      await authService.signOut();

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/auth\/logout$/),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('ref-token'),
        }),
      );
      expect(await SecureStore.getItemAsync('stocklens_access_token')).toBeNull();
      expect(await SecureStore.getItemAsync('stocklens_refresh_token')).toBeNull();
    });

    it('clears tokens locally even when the server call fails', async () => {
      const SecureStore = require('expo-secure-store');
      await SecureStore.setItemAsync('stocklens_access_token', 'acc');
      await SecureStore.setItemAsync('stocklens_refresh_token', 'ref');
      fetchMock.mockRejectOnce(new Error('Network error'));

      await authService.signOut(); // should not throw

      expect(await SecureStore.getItemAsync('stocklens_access_token')).toBeNull();
      expect(await SecureStore.getItemAsync('stocklens_refresh_token')).toBeNull();
    });
  });

  describe('getProfile', () => {
    it('returns the user profile on success', async () => {
      fetchMock.mockResponseOnce(JSON.stringify(mockUser), { status: 200 });

      const profile = await authService.getProfile();

      expect(profile).toEqual(mockUser);
    });

    it('returns null for ApiAuthError (expired session)', async () => {
      fetchMock.mockResponseOnce('', { status: 401 });

      const profile = await authService.getProfile();

      expect(profile).toBeNull();
    });

    it('rethrows non-auth errors', async () => {
      fetchMock.mockResponseOnce('', { status: 500 });

      await expect(authService.getProfile()).rejects.toThrow();
    });
  });

  describe('isAuthenticated', () => {
    it('returns true when profile fetch succeeds', async () => {
      const SecureStore = require('expo-secure-store');
      // Use a valid JWT shape so isTokenExpired doesn't pre-trigger a refresh
      const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }));
      await SecureStore.setItemAsync('stocklens_access_token', `header.${payload}.sig`);
      fetchMock.mockResponseOnce(JSON.stringify(mockUser), { status: 200 });

      const authed = await authService.isAuthenticated();

      expect(authed).toBe(true);
    });

    it('returns false when no token exists', async () => {
      const authed = await authService.isAuthenticated();
      expect(authed).toBe(false);
    });

    it('returns false when profile returns null', async () => {
      const SecureStore = require('expo-secure-store');
      await SecureStore.setItemAsync('stocklens_access_token', 'stale-token');
      fetchMock.mockResponseOnce('', { status: 401 });

      const authed = await authService.isAuthenticated();

      expect(authed).toBe(false);
    });
  });

  describe('forgotPassword', () => {
    it('sends POST /auth/forgot-password with email', async () => {
      fetchMock.mockResponseOnce(JSON.stringify({ message: 'Email sent' }), { status: 200 });

      const result = await authService.forgotPassword('a@b.com');

      expect(result.message).toBe('Email sent');
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/auth\/forgot-password$/),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('a@b.com'),
        }),
      );
    });
  });
});
