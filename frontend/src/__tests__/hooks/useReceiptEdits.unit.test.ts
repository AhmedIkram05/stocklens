/**
 * Tests for `useReceiptEdits` — submit/validation logic for the editable
 * receipt fields (category, merchant, amount, date).
 */

import { act, renderHook } from '@testing-library/react-native';
import { Alert } from 'react-native';
import useReceiptEdits from '@/hooks/useReceiptEdits';
import { receiptService } from '@/services/receipts';
import { emit } from '@/services/eventBus';

jest.mock('@/services/receipts', () => ({
  receiptService: { update: jest.fn() },
}));
jest.mock('@/services/eventBus', () => ({ emit: jest.fn() }));

const mockedUpdate = receiptService.update as jest.MockedFunction<typeof receiptService.update>;
const mockedEmit = emit as jest.MockedFunction<typeof emit>;

describe('useReceiptEdits', () => {
  let alertSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    mockedUpdate.mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  const setup = async (receiptId: string | undefined) =>
    await renderHook(() => useReceiptEdits({ receiptId, setReceipt: jest.fn() }));

  it('rejects an invalid amount without calling the service', async () => {
    const { result } = await setup('r1');
    await act(async () => {
      result.current.setAmountEditValue('abc');
    });
    await act(async () => {
      await result.current.handleUpdateAmount();
    });
    expect(alertSpy).toHaveBeenCalledWith('Invalid amount', 'Enter a valid positive number');
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it('persists a valid amount, closes the modal and emits change', async () => {
    const { result } = await setup('r1');
    await act(async () => {
      result.current.setAmountEditValue('99.99');
    });
    await act(async () => {
      await result.current.handleUpdateAmount();
    });
    expect(mockedUpdate).toHaveBeenCalledWith('r1', { total_amount: 99.99 });
    expect(mockedEmit).toHaveBeenCalledWith('receipts-changed', { id: 'r1', action: 'updated' });
    expect(result.current.amountModalVisible).toBe(false);
  });

  it('rejects a malformed date', async () => {
    const { result } = await setup('r1');
    await act(async () => {
      result.current.setDateEditValue('2024/01/01');
    });
    await act(async () => {
      await result.current.handleUpdateDate();
    });
    expect(alertSpy).toHaveBeenCalledWith('Invalid date', 'Enter date as YYYY-MM-DD');
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it('ignores a whitespace-only merchant edit', async () => {
    const { result } = await setup('r1');
    await act(async () => {
      result.current.setMerchantEditValue('   ');
    });
    await act(async () => {
      await result.current.handleUpdateMerchant();
    });
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it('does nothing without a receipt id', async () => {
    const { result } = await setup(undefined);
    await act(async () => {
      result.current.setAmountEditValue('10');
    });
    await act(async () => {
      await result.current.handleUpdateAmount();
      await result.current.handleSelectCategory('cat-1');
    });
    expect(mockedUpdate).not.toHaveBeenCalled();
  });
});
