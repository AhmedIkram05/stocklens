/**
 * Tests for `useDepositFlow` — portfolio loading and receipt-sourced deposit.
 */

import { act, renderHook } from '@testing-library/react-native';
import { Alert } from 'react-native';
import useDepositFlow from '@/hooks/useDepositFlow';
import { portfolioService } from '@/services/portfolios';

jest.mock('@/services/portfolios', () => ({
  portfolioService: { listPortfolios: jest.fn(), createCashFlow: jest.fn() },
}));

const mockedList = portfolioService.listPortfolios as jest.MockedFunction<
  typeof portfolioService.listPortfolios
>;
const mockedCash = portfolioService.createCashFlow as jest.MockedFunction<
  typeof portfolioService.createCashFlow
>;

describe('useDepositFlow', () => {
  let alertSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  });

  const setup = async () =>
    await renderHook(() =>
      useDepositFlow({ totalAmount: 42, receiptId: 'r1', formattedAmount: '£42.00' }),
    );

  it('opens the modal and loads portfolios', async () => {
    mockedList.mockResolvedValue([{ id: 'p1', name: 'Main', created_at: '', updated_at: '' }]);
    const { result } = await setup();
    await act(async () => {
      await result.current.handleOpenDeposit();
    });
    expect(result.current.depositModalVisible).toBe(true);
    expect(result.current.portfolioList).toHaveLength(1);
    expect(result.current.portfoliosLoading).toBe(false);
  });

  it('records a receipt-sourced cash flow and confirms', async () => {
    mockedCash.mockResolvedValue({} as any);
    const { result } = await setup();
    await act(async () => {
      await result.current.handleSelectPortfolio('p1');
    });
    expect(mockedCash).toHaveBeenCalledWith('p1', {
      amount: 42,
      source: 'receipt',
      source_id: 'r1',
      notes: 'Deposit from £42.00 receipt',
    });
    expect(alertSpy).toHaveBeenCalledWith(
      'Deposited',
      expect.stringContaining('deposited into portfolio'),
    );
    expect(result.current.depositModalVisible).toBe(false);
  });

  it('reports a failed deposit', async () => {
    mockedCash.mockRejectedValue(new Error('nope'));
    const { result } = await setup();
    await act(async () => {
      await result.current.handleSelectPortfolio('p1');
    });
    expect(alertSpy).toHaveBeenCalledWith('Error', 'Failed to deposit. Please try again.');
  });

  it('closes the modal when portfolios fail to load', async () => {
    mockedList.mockRejectedValue(new Error('offline'));
    const { result } = await setup();
    await act(async () => {
      await result.current.handleOpenDeposit();
    });
    expect(alertSpy).toHaveBeenCalledWith('Error', 'Could not load portfolios');
    expect(result.current.depositModalVisible).toBe(false);
  });
});
