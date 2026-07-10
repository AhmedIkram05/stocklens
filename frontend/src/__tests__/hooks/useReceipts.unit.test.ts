/**
 * Tests for `useReceipts` hook.
 * Verifies initial fetch via `receiptService.list()`, event-bus driven refresh,
 * polling behavior, data normalization for UI, and error/cleanup handling.
 */

import { act, renderHook, waitFor } from '@testing-library/react-native';
import useReceipts from '@/hooks/useReceipts';
import { receiptService } from '@/services/receipts';
import { subscribe } from '@/services/eventBus';
import { createApiReceipt } from '../fixtures';

// useFocusEffect needs a NavigationContainer; the hook's focus-refetch isn't
// under test here, so stub it to a no-op.
jest.mock('@react-navigation/native', () => ({
  useFocusEffect: jest.fn(),
}));

// Handler type used by the mocked event bus
type ReceiptsChangedHandler = (payload?: Record<string, unknown>) => void;

// Mock the receipt service and event bus to avoid HTTP calls
jest.mock('@/services/receipts', () => ({
  receiptService: {
    list: jest.fn(),
  },
}));

jest.mock('@/services/eventBus', () => ({
  subscribe: jest.fn(),
}));

const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;
const mockedSubscribe = subscribe as jest.MockedFunction<typeof subscribe>;

describe('useReceipts', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  /**
   * Test: Fetch, refresh, and cleanup
   * - Verifies initial fetch (no userId needed — backend uses JWT)
   * - Ensures the hook responds to event bus notifications by re-fetching
   * - Verifies periodic refresh via timers and cleanup/unsubscribe on unmount
   */
  it('fetches receipts, refreshes on events, and cleans up on unmount', async () => {
    jest.useFakeTimers();
    const unsubSpy = jest.fn();
    const handlers: ReceiptsChangedHandler[] = [];
    mockedSubscribe.mockImplementation((_event: string, handler: ReceiptsChangedHandler) => {
      handlers.push(handler);
      return unsubSpy;
    });

    // Initial response returned by mocked service
    const receipt1 = createApiReceipt({
      id: '7',
      total_amount: 42.5,
      scanned_at: '2025-01-01T10:00:00Z',
      receipt_image_s3_key: 's3://key/1',
    });
    mockedReceiptService.list.mockResolvedValueOnce([receipt1]);

    const { result, unmount } = renderHook(() => useReceipts());

    // Wait until loading completes
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Verify initial fetch (no args — defaults handled by real impl)
    expect(mockedReceiptService.list).toHaveBeenCalledWith();
    expect(result.current.receipts).toEqual([
      {
        id: '7',
        label: expect.any(String),
        amount: 42.5,
        date: '2025-01-01T10:00:00Z',
        time: '',
        image: 's3://key/1',
        categoryId: null,
        source: undefined,
        confidence: undefined,
      },
    ]);

    // Simulate event bus telling hook to refresh
    const receipt2 = createApiReceipt({
      id: '8',
      total_amount: 99.99,
      scanned_at: '2025-01-05T12:00:00Z',
    });
    mockedReceiptService.list.mockResolvedValueOnce([receipt2]);

    await act(async () => {
      await handlers[0]?.();
    });

    await waitFor(() => expect(result.current.receipts[0].id).toBe('8'));

    // Advance timers for periodic refresh
    act(() => {
      jest.advanceTimersByTime(30000);
    });
    expect(mockedReceiptService.list).toHaveBeenCalledTimes(3);

    // Unmount should unsubscribe
    unmount();
    expect(unsubSpy).toHaveBeenCalled();
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  /**
   * Test: Error handling on fetch
   */
  it('captures fetch errors', async () => {
    mockedReceiptService.list.mockRejectedValueOnce(new Error('boom'));

    const { result } = renderHook(() => useReceipts());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('boom');
  });
});
