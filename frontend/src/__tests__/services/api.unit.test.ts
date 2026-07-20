/**
 * Tests for `api.ts` — the HTTP client with JWT auto-refresh.
 *
 * Covers token injection, pre-emptive refresh, 401 → refresh → retry,
 * error parsing, 204 handling, and the convenience wrapper methods.
 *
 * All HTTP is mocked via jest-fetch-mock (configured in jest.setup.ts).
 * SecureStore is mocked in jest.setup.ts (in-memory Map).
 */

import { api, apiService, ApiError, ApiAuthError } from '@/services/api';
import * as SecureStore from 'expo-secure-store';

const fetchMock = require('jest-fetch-mock');

const ACCESS_TOKEN_KEY = 'stocklens_access_token';
const REFRESH_TOKEN_KEY = 'stocklens_refresh_token';

// Helper to set a valid-looking JWT in SecureStore.
// exp = now + 3600s (1 hour from now)
function setValidToken(expOffset = 3600): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expOffset }));
  const token = `header.${payload}.sig`;
  SecureStore.setItemAsync(ACCESS_TOKEN_KEY, token);
  return token;
}

function setExpiredToken(): string {
  const token = setValidToken(-3600); // expired 1 hour ago
  return token;
}

function setRefreshToken(): void {
  SecureStore.setItemAsync(REFRESH_TOKEN_KEY, 'refresh-token-val');
}

describe('api()', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('sends a GET request and returns parsed JSON', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ key: 'value' }), { status: 200 });

    const result = await api('/test');

    expect(result).toEqual({ key: 'value' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/test$/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('sends POST with JSON body', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 1 }), { status: 201 });
    const body = { name: 'test' };

    const result = await api('/items', { method: 'POST', body });

    expect(result).toEqual({ id: 1 });
    const callBody = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(callBody).toEqual(body);
  });

  it('returns undefined for 204 No Content', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    const result = await api('/delete-me', { method: 'DELETE' });

    expect(result).toBeUndefined();
  });

  it('injects Bearer token from SecureStore', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({ ok: true }), { status: 200 });

    await api('/me');

    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['Authorization']).toMatch(/^Bearer /);
  });

  it('skips auth header when skipAuth is true', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({ ok: true }), { status: 200 });

    await api('/public', { skipAuth: true });

    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['Authorization']).toBeUndefined();
  });

  it('pre-emptively refreshes an expired token before the request', async () => {
    setExpiredToken();
    setRefreshToken();
    fetchMock.mockResponseOnce(
      JSON.stringify({ access_token: 'new-access', refresh_token: 'new-refresh' }),
      { status: 200 },
    );
    fetchMock.mockResponseOnce(JSON.stringify({ ok: true }), { status: 200 });

    await api('/me');

    // First call should be POST /auth/refresh
    expect(fetchMock.mock.calls[0][0]).toContain('/auth/refresh');
    // Second call should be the actual request with new token
    expect(fetchMock.mock.calls[1][0]).toContain('/me');
  });

  it('throws ApiAuthError when pre-emptive refresh fails', async () => {
    setExpiredToken();
    SecureStore.setItemAsync(REFRESH_TOKEN_KEY, ''); // no refresh token

    await expect(api('/me')).rejects.toThrow(ApiAuthError);
  });

  it('retries once on 401 and returns result on success', async () => {
    setValidToken();
    setRefreshToken();
    // First request returns 401
    fetchMock.mockResponseOnce('', { status: 401 });
    // Refresh succeeds
    fetchMock.mockResponseOnce(
      JSON.stringify({ access_token: 'new-access', refresh_token: 'new-refresh' }),
      { status: 200 },
    );
    // Retry succeeds
    fetchMock.mockResponseOnce(JSON.stringify({ ok: true }), { status: 200 });

    const result = await api('/me');

    expect(result).toEqual({ ok: true });
    // 3 calls: GET /me → POST /auth/refresh → GET /me
    expect(fetchMock.mock.calls).toHaveLength(3);
  });

  it('throws ApiAuthError when 401 refresh fails', async () => {
    setValidToken();
    SecureStore.setItemAsync(REFRESH_TOKEN_KEY, '');
    fetchMock.mockResponseOnce('', { status: 401 });

    await expect(api('/me')).rejects.toThrow(ApiAuthError);
  });

  it('throws ApiError with parsed detail on non-401 error', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Not found' }), { status: 404 });

    const err = await api('/items/999').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 404, message: 'Not found' });
  });

  it('throws ApiError with statusText when response body is not JSON', async () => {
    setValidToken();
    fetchMock.mockResponseOnce('not json', { status: 500, statusText: 'Internal Server Error' });

    const err = await api('/boom').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 500 });
  });

  it('merges custom headers with defaults', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({}), { status: 200 });

    await api('/test', { headers: { 'X-Custom': 'val' } });

    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-Custom']).toBe('val');
    expect(headers['Content-Type']).toBe('application/json');
  });
});

describe('apiService convenience methods', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('get calls api with GET method', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({}), { status: 200 });
    await apiService.get('/items');
    expect(fetchMock.mock.calls[0][1].method).toBe('GET');
  });

  it('post calls api with POST method and body', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({}), { status: 201 });
    await apiService.post('/items', { name: 'x' });
    expect(fetchMock.mock.calls[0][1].method).toBe('POST');
  });

  it('put calls api with PUT method and body', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });
    await apiService.put('/items/1', { name: 'y' });
    expect(fetchMock.mock.calls[0][1].method).toBe('PUT');
  });

  it('delete calls api with DELETE method', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });
    await apiService.delete('/items/1');
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });
});

describe('token management', () => {
  beforeEach(async () => {
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('getAccessToken returns stored token', async () => {
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, 'my-token');
    expect(await apiService.getAccessToken()).toBe('my-token');
  });

  it('getRefreshToken returns stored refresh token', async () => {
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, 'my-refresh');
    expect(await apiService.getRefreshToken()).toBe('my-refresh');
  });

  it('setTokens persists both tokens', async () => {
    await apiService.setTokens('acc', 'ref');
    expect(await SecureStore.getItemAsync(ACCESS_TOKEN_KEY)).toBe('acc');
    expect(await SecureStore.getItemAsync(REFRESH_TOKEN_KEY)).toBe('ref');
  });

  it('clearTokens removes both tokens', async () => {
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, 'a');
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, 'r');
    await apiService.clearTokens();
    expect(await SecureStore.getItemAsync(ACCESS_TOKEN_KEY)).toBeNull();
    expect(await SecureStore.getItemAsync(REFRESH_TOKEN_KEY)).toBeNull();
  });
});

describe('edge cases', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('handles empty refresh token gracefully', async () => {
    setExpiredToken();
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, '   '); // whitespace

    fetchMock.mockResponseOnce('', { status: 401 });

    await expect(api('/me')).rejects.toThrow(ApiAuthError);
  });

  it('patches data correctly', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ updated: true }), { status: 200 });

    const result = await api('/items/1', { method: 'PATCH', body: { name: 'new' } });

    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH');
    expect(result).toEqual({ updated: true });
  });

  it('handles network error (no response)', async () => {
    fetchMock.mockRejectOnce(new Error('Network request failed'));
    setValidToken();

    const err = await api('/test').catch((e) => e);
    expect(err).toBeInstanceOf(Error);
  });
});

describe('parseError branches', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('throws ApiError with message field from JSON body (line 120)', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({ message: 'Validation failed' }), { status: 400 });

    const err = await api('/test').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 400, message: 'Validation failed' });
  });

  it('throws ApiError with stringified body when no detail or message field (line 121)', async () => {
    setValidToken();
    const body = { foo: 'bar' };
    fetchMock.mockResponseOnce(JSON.stringify(body), { status: 400 });

    const err = await api('/test').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 400, message: JSON.stringify(body) });
  });

  it('uses statusText when response body is empty and not JSON (line 127)', async () => {
    setValidToken();
    fetchMock.mockResponseOnce('', { status: 502, statusText: 'Bad Gateway' });

    const err = await api('/bad-gateway').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 502, message: 'Bad Gateway' });
  });
});

describe('api() 401 retry with failed retry', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('throws ApiError when 401 refresh succeeds but retry returns non-ok (lines 204-205)', async () => {
    setValidToken();
    setRefreshToken();
    fetchMock.mockResponseOnce('', { status: 401 });
    fetchMock.mockResponseOnce(
      JSON.stringify({ access_token: 'new-access', refresh_token: 'new-refresh' }),
      { status: 200 },
    );
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Forbidden' }), { status: 403 });

    const err = await api('/admin').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 403, message: 'Forbidden' });
    expect(fetchMock.mock.calls).toHaveLength(3);
  });
});

describe('apiService.upload()', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('pre-emptively refreshes expired token before upload (lines 261-265)', async () => {
    setExpiredToken();
    setRefreshToken();
    fetchMock.mockResponseOnce(
      JSON.stringify({ access_token: 'new-access', refresh_token: 'new-refresh' }),
      { status: 200 },
    );
    fetchMock.mockResponseOnce(JSON.stringify({ uploaded: true }), { status: 200 });

    const formData = new FormData();
    formData.append('file', 'test');
    const result = await apiService.upload('/upload', formData);

    expect(result).toEqual({ uploaded: true });
    expect(fetchMock.mock.calls[0][0]).toContain('/auth/refresh');
    expect(fetchMock.mock.calls[1][0]).toContain('/upload');
  });

  it('throws ApiAuthError when pre-emptive refresh fails for upload (line 267)', async () => {
    setExpiredToken();
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);

    const formData = new FormData();
    formData.append('file', 'test');

    await expect(apiService.upload('/upload', formData)).rejects.toThrow(ApiAuthError);
  });

  it('retries upload on 401 and throws ApiError on retry failure (lines 290-304)', async () => {
    setValidToken();
    setRefreshToken();
    fetchMock.mockResponseOnce('', { status: 401 });
    fetchMock.mockResponseOnce(
      JSON.stringify({ access_token: 'new-access', refresh_token: 'new-refresh' }),
      { status: 200 },
    );
    fetchMock.mockResponseOnce(JSON.stringify({ message: 'Upload failed' }), { status: 409 });

    const formData = new FormData();
    formData.append('file', 'test');
    const err = await apiService.upload('/upload', formData).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, message: 'Upload failed' });
    expect(fetchMock.mock.calls).toHaveLength(3);
  });
});

describe('ensureValidAccessToken', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('returns null when no token stored', async () => {
    const result = await apiService.ensureValidAccessToken();
    expect(result).toBeNull();
  });

  it('returns existing token when not expired', async () => {
    const token = setValidToken();
    const result = await apiService.ensureValidAccessToken();
    expect(result).toBe(token);
  });

  it('refreshes expired token and returns new access token (lines 330-336)', async () => {
    setExpiredToken();
    setRefreshToken();
    fetchMock.mockResponseOnce(
      JSON.stringify({ access_token: 'refreshed-access', refresh_token: 'new-refresh' }),
      { status: 200 },
    );

    const result = await apiService.ensureValidAccessToken();
    expect(result).toBe('refreshed-access');
    expect(fetchMock.mock.calls[0][0]).toContain('/auth/refresh');
  });

  it('returns null when refresh of expired token fails (lines 330-338)', async () => {
    setExpiredToken();
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);

    const result = await apiService.ensureValidAccessToken();
    expect(result).toBeNull();
  });

  it('returns null for malformed token payload — decodeJWT catch (line 35)', async () => {
    // Payload is valid base64 but NOT valid JSON, so JSON.parse inside
    // decodeJWT throws, the catch block returns null, and isTokenExpired
    // treats it as expired. No refresh token → ensureValidAccessToken returns null.
    const badToken = 'header.' + btoa('not-json') + '.sig';
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, badToken);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);

    const result = await apiService.ensureValidAccessToken();
    expect(result).toBeNull();
  });
});
