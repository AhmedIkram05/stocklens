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
    const receipts = [
      { id: '1', total_amount: 10 },
      { id: '2', total_amount: 20 },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ receipts, total: 2, limit: 50, offset: 0 }), {
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

  it('deleteAll deletes each receipt and repeats until the list is empty', async () => {
    const receipts = [
      { id: '1', total_amount: 10 },
      { id: '2', total_amount: 20 },
    ];
    fetchMock.mockResponses(
      [JSON.stringify({ receipts, total: 2, limit: 1000, offset: 0 }), { status: 200 }],
      ['', { status: 204 }],
      ['', { status: 204 }],
      [JSON.stringify({ receipts: [], total: 0, limit: 1000, offset: 0 }), { status: 200 }],
    );

    const deleted = await receiptService.deleteAll();

    expect(deleted).toBe(2);
    // Should have listed, deleted each, then re-listed to confirm empty
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
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      expect.stringMatching(/\/receipts\?limit=1000&offset=0/),
      expect.any(Object),
    );
  });

  it('deleteAll keeps paging when the backend returns partial pages', async () => {
    fetchMock.mockResponses(
      [
        JSON.stringify({ receipts: [{ id: '1' }, { id: '2' }], total: 3, limit: 2, offset: 0 }),
        { status: 200 },
      ],
      ['', { status: 204 }],
      ['', { status: 204 }],
      [JSON.stringify({ receipts: [{ id: '3' }], total: 3, limit: 2, offset: 2 }), { status: 200 }],
      ['', { status: 204 }],
      [JSON.stringify({ receipts: [], total: 3, limit: 2, offset: 3 }), { status: 200 }],
    );

    const deleted = await receiptService.deleteAll();

    expect(deleted).toBe(3);
    expect(
      fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).includes('/receipts?'))
        .length,
    ).toBe(3);
  });

  it('deleteAll never exceeds 10 concurrent deletes', async () => {
    const ids = Array.from({ length: 25 }, (_, i) => ({ id: `${i + 1}`, total_amount: 1 }));
    fetchMock.mockResponses(
      [JSON.stringify({ receipts: ids, total: 25, limit: 1000, offset: 0 }), { status: 200 }],
      ...ids.map(() => ['', { status: 204 }] as Parameters<typeof fetchMock.mockResponseOnce>),
      [JSON.stringify({ receipts: [], total: 0, limit: 1000, offset: 0 }), { status: 200 }],
    );
    const originalDelete = receiptService.delete.bind(receiptService);
    let inFlight = 0;
    let peak = 0;
    jest.spyOn(receiptService, 'delete').mockImplementation(async (id: string) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      try {
        await originalDelete(id);
      } finally {
        inFlight -= 1;
      }
    });

    const deleted = await receiptService.deleteAll();

    expect(deleted).toBe(25);
    expect(peak).toBeLessThanOrEqual(10);
    expect(peak).toBeGreaterThan(1);
  });
});
