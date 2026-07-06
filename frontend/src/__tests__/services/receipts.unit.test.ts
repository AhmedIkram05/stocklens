/**
 * Tests for `receipts.ts` — the receipt service layer.
 *
 * Covers cascade scan (happy path + error handling), CRUD operations,
 * and health-check endpoint.
 *
 * HTTP is mocked via jest-fetch-mock (global, configured in jest.setup.ts).
 */

import { receiptService } from '@/services/receipts';
import { ApiError, ApiAuthError } from '@/services/api';
import * as SecureStore from 'expo-secure-store';

const fetchMock = require('jest-fetch-mock');

const ACCESS_TOKEN_KEY = 'stocklens_access_token';
const REFRESH_TOKEN_KEY = 'stocklens_refresh_token';

// Helper: set a valid JWT in SecureStore for auth-gated requests.
function setValidToken(): void {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }));
  SecureStore.setItemAsync(ACCESS_TOKEN_KEY, `header.${payload}.sig`);
}

function setRefreshToken(): void {
  SecureStore.setItemAsync(REFRESH_TOKEN_KEY, 'refresh-token-val');
}

describe('receiptService.scan() — cascade OCR endpoint', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('sends FormData to /receipts/scan and returns ScanResponse on success', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(
      JSON.stringify({
        id: 'receipt-abc',
        extraction: {
          merchant_name: 'Tesco',
          total: 42.5,
          date: '2025-01-15',
          currency: 'GBP',
          items: [{ name: 'Milk', quantity: 1, price: 1.5 }],
        },
        raw_text: 'Total: £42.50',
        source: 'cascade',
        confidence: 0.96,
        processing_time_ms: 892,
      }),
      { status: 200 },
    );

    const result = await receiptService.scan('file:///photo.jpg');

    // Correct endpoint and method
    expect(fetchMock.mock.calls[0][0]).toContain('/receipts/scan');
    expect(fetchMock.mock.calls[0][1].method).toBe('POST');

    // Body was sent (non-empty)
    expect(fetchMock.mock.calls[0][1].body).toBeTruthy();

    // Response shape
    expect(result).toMatchObject({
      id: 'receipt-abc',
      source: 'cascade',
      confidence: 0.96,
    });
    expect(result.extraction.total).toBe(42.5);
  });

  it('throws ApiError when cascade endpoint returns 500', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Internal cascade processing error' }), {
      status: 500,
    });

    await expect(receiptService.scan('file:///bad.jpg')).rejects.toThrow(ApiError);
  });

  it('throws ApiError with parsed detail message on 400', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'No receipt text found in image' }), {
      status: 400,
    });

    const err = await receiptService.scan('file:///empty.jpg').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 400, message: 'No receipt text found in image' });
  });

  it('throws on network failure (no response)', async () => {
    fetchMock.mockRejectOnce(new Error('Network request failed'));

    await expect(receiptService.scan('file:///offline.jpg')).rejects.toThrow(
      'Network request failed',
    );
  });

  it('propagates 401 when refresh also fails', async () => {
    setValidToken();
    setRefreshToken();
    // First request returns 401
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 });
    // Refresh also fails
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Invalid refresh' }), { status: 401 });

    await expect(receiptService.scan('file:///protected.jpg')).rejects.toThrow(ApiAuthError);
  });

  it('handles 204 empty response', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    const result = await receiptService.scan('file:///noop.jpg');
    expect(result).toBeUndefined();
  });
});

describe('receiptService CRUD', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('create() POSTs to /receipts', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 'r1', total_amount: 10 }), { status: 201 });

    const result = await receiptService.create({ total_amount: 10 });
    expect(result.id).toBe('r1');
    expect(fetchMock.mock.calls[0][0]).toContain('/receipts');
    expect(fetchMock.mock.calls[0][1].method).toBe('POST');
  });

  it('list() GETs /receipts and returns items', async () => {
    const items = [
      { id: '1', total_amount: 10 },
      { id: '2', total_amount: 20 },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ items, total: 2, limit: 50, offset: 0 }), {
      status: 200,
    });

    const result = await receiptService.list();
    expect(result).toHaveLength(2);
    expect(fetchMock.mock.calls[0][0]).toContain('/receipts?limit=50&offset=0');
  });

  it('getById() returns null on 404', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Not found' }), { status: 404 });

    const result = await receiptService.getById('nonexistent');
    expect(result).toBeNull();
  });

  it('getById() rethrows non-404 errors', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Server error' }), { status: 500 });

    await expect(receiptService.getById('r1')).rejects.toThrow(ApiError);
  });

  it('delete() sends DELETE request', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    await receiptService.delete('r1');
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
    expect(fetchMock.mock.calls[0][0]).toContain('/receipts/r1');
  });

  it('update() sends PUT request', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    await receiptService.update('r1', { merchant_name: 'Updated' });
    expect(fetchMock.mock.calls[0][1].method).toBe('PUT');
    expect(fetchMock.mock.calls[0][0]).toContain('/receipts/r1');
  });
});

describe('receiptService.checkHealth()', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('returns health status from /receipts/cascade/health', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        status: 'healthy',
        checks: { ocr: 'ok', nlp: 'ok', aggregator: 'ok' },
        cascade_threshold: 0.6,
      }),
      { status: 200 },
    );

    const result = await receiptService.checkHealth();
    expect(result.status).toBe('healthy');
    expect(fetchMock.mock.calls[0][0]).toContain('/receipts/cascade/health');
  });

  it('throws when health endpoint is down', async () => {
    fetchMock.mockResponseOnce('', { status: 503 });

    await expect(receiptService.checkHealth()).rejects.toThrow();
  });
});
