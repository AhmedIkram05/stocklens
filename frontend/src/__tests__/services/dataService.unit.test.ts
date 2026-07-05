/**
 * Tests for the API-based receipt service (`@/services/receipts`).
 *
 * Exercises create, list, getById, update, delete, deleteAll with mocked HTTP.
 * The service delegates to `apiService` — we mock fetch via jest-fetch-mock.
 */

import { receiptService } from '@/services/receipts';

const fetchMock = require('jest-fetch-mock');

describe('receiptService (API)', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('create sends POST and returns created receipt', async () => {
    const created = {
      id: '1',
      total_amount: 12.5,
      ocr_raw_text: 'Total: $12.50',
    };
    fetchMock.mockResponseOnce(JSON.stringify(created), { status: 201 });

    const result = await receiptService.create({
      total_amount: 12.5,
      ocr_raw_text: 'Total: $12.50',
    });

    expect(result).toMatchObject(created);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/receipts$/),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"total_amount"'),
      }),
    );
  });

  it('list sends GET and returns items array', async () => {
    const items = [
      { id: '1', total_amount: 10 },
      { id: '2', total_amount: 20 },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ items, total: 2, limit: 50, offset: 0 }), {
      status: 200,
    });

    const result = await receiptService.list();

    expect(result).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/receipts\?limit=50&offset=0/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('getById returns receipt when found', async () => {
    const receipt = { id: '42', total_amount: 99 };
    fetchMock.mockResponseOnce(JSON.stringify(receipt), { status: 200 });

    const result = await receiptService.getById('42');

    expect(result).toMatchObject(receipt);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/receipts\/42$/),
      expect.any(Object),
    );
  });

  it('getById returns null on 404', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Not found' }), { status: 404 });

    const result = await receiptService.getById('999');

    expect(result).toBeNull();
  });

  it('update sends PUT with partial data', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    await receiptService.update('7', { total_amount: 88.8 });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/receipts\/7$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('delete sends DELETE', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    await receiptService.delete('7');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/receipts\/7$/),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('deleteAll fetches all then deletes each', async () => {
    const items = [
      { id: '1', total_amount: 10 },
      { id: '2', total_amount: 20 },
    ];
    fetchMock.mockResponses(
      [JSON.stringify({ items, total: 2, limit: 1000, offset: 0 }), { status: 200 }],
      ['', { status: 204 }],
      ['', { status: 204 }],
    );

    await receiptService.deleteAll();

    // Should have fetched list and then deleted each
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringMatching(/\/receipts\?limit=1000&offset=0/),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringMatching(/\/receipts\/1$/),
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      expect.stringMatching(/\/receipts\/2$/),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });
});
