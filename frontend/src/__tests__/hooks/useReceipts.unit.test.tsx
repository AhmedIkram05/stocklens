/**
 * Tests for `useReceipts` (unit).
 * Verifies fetch, mapping, event subscription, and error handling.
 */

import { renderHook, waitFor, act } from '@testing-library/react-native';
import useReceipts from '@/hooks/useReceipts';

jest.mock('@/services/receipts', () => ({
  receiptService: {
    list: jest.fn(),
  },
}));

jest.mock('@/services/eventBus', () => ({
  subscribe: jest.fn(() => jest.fn()),
  emit: jest.fn(),
}));

jest.mock('@react-navigation/native', () => ({
  useFocusEffect: jest.fn((cb: () => void) => cb()),
}));

const mockedList = jest.requireMock('@/services/receipts').receiptService.list as jest.Mock;

describe('useReceipts', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('returns loading=true initially', () => {
    mockedList.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useReceipts());
    expect(result.current.loading).toBe(true);
    expect(result.current.receipts).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('returns receipts when fetch succeeds', async () => {
    mockedList.mockResolvedValue([
      {
        id: 'receipt-1',
        total_amount: 12.34,
        scanned_at: '2025-06-15T10:30:00Z',
        receipt_image_s3_key: 's3://receipts/img.jpg',
        source: 'regex',
        ocr_confidence: 95,
        category_id: 'cat-1',
      },
    ]);

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.receipts).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it('returns error when fetch fails', async () => {
    mockedList.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.receipts).toEqual([]);
    expect(result.current.error).toBe('Network error');
  });

  it('handles empty receipt list', async () => {
    mockedList.mockResolvedValue([]);

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.receipts).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('maps receipt fields correctly', async () => {
    mockedList.mockResolvedValue([
      {
        id: 'receipt-1',
        total_amount: 12.34,
        scanned_at: '2025-06-15T10:30:00Z',
        receipt_image_s3_key: 's3://receipts/img.jpg',
        source: 'regex',
        ocr_confidence: 95,
        category_id: 'cat-1',
      },
    ]);

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const receipt = result.current.receipts[0];
    expect(receipt.id).toBe('receipt-1');
    expect(receipt.amount).toBe(12.34);
    expect(receipt.date).toBe('2025-06-15T10:30:00Z');
    expect(receipt.image).toBe('s3://receipts/img.jpg');
    expect(receipt.source).toBe('regex');
    expect(receipt.confidence).toBe(95);
    expect(receipt.categoryId).toBe('cat-1');
  });

  it('handles receipt with missing fields gracefully', async () => {
    mockedList.mockResolvedValue([
      {
        id: 'receipt-minimal',
        total_amount: null,
        scanned_at: null,
        receipt_image_s3_key: null,
      },
    ]);

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const receipt = result.current.receipts[0];
    expect(receipt.id).toBe('receipt-minimal');
    expect(receipt.amount).toBe(0);
    expect(receipt.date).toBe('');
    expect(receipt.image).toBeUndefined();
    expect(receipt.source).toBeUndefined();
    expect(receipt.confidence).toBeUndefined();
    expect(receipt.categoryId).toBeNull();
  });

  it('provides refetch function that fetches silently', async () => {
    mockedList.mockResolvedValue([]);

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(mockedList).toHaveBeenCalledTimes(1);

    mockedList.mockResolvedValue([
      {
        id: 'receipt-2',
        total_amount: 99.99,
        scanned_at: '2025-06-16T10:30:00Z',
      },
    ]);

    await act(async () => {
      result.current.refetch();
    });

    await waitFor(() => {
      expect(result.current.receipts).toHaveLength(1);
      expect(result.current.receipts[0].id).toBe('receipt-2');
    });
  });
});
