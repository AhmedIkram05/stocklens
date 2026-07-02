/**
 * Integration tests for `SummaryScreen`.
 * Verifies empty state, spending statistics, insights expansion, and
 * prefetch subscription behavior used for projections.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import SummaryScreen from '@/screens/SummaryScreen';
import useReceipts, { ReceiptShape } from '@/hooks/useReceipts';
import { renderWithProviders } from '../utils';
import { subscribe } from '@/services/eventBus';
import { useNavigation } from '@react-navigation/native';
import { createReceipt } from '../fixtures';

jest.mock('@/hooks/useReceipts');

jest.mock('@/services/eventBus', () => ({
  subscribe: jest.fn(() => jest.fn()),
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(),
  };
});

const mockedUseReceipts = useReceipts as jest.MockedFunction<typeof useReceipts>;
const mockedSubscribe = subscribe as jest.MockedFunction<typeof subscribe>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

let navigateSpy: jest.Mock;
let goBackSpy: jest.Mock;

describe('SummaryScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseReceipts.mockReturnValue({ receipts: [], loading: false, error: null } as any);
    navigateSpy = jest.fn();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({
      navigate: navigateSpy,
      goBack: goBackSpy,
    } as any);
  });

  it('shows onboarding empty state when no receipts exist and navigates to Scan on CTA press', () => {
    const { getByText } = renderWithProviders(<SummaryScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByText('No Data Yet')).toBeTruthy();

    fireEvent.press(getByText('Scan Your First Receipt'));

    expect(navigateSpy).toHaveBeenCalledWith('Scan');
    expect(mockedSubscribe).toHaveBeenCalledWith('historical-updated', expect.any(Function));
  });

  it('renders spending stats and expands dynamic insight content', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '2 weeks ago',
        amount: 120,
        date: createReceipt({ total_amount: 120, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 120, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
      },
      {
        id: '2',
        label: '10 days ago',
        amount: 45,
        date: createReceipt({ total_amount: 45, date_scanned: '2024-02-14T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 45, date_scanned: '2024-02-14T00:00:00.000Z' })
          .image_uri!,
      },
      {
        id: '3',
        label: '6 weeks ago',
        amount: 35,
        date: createReceipt({ total_amount: 35, date_scanned: '2024-01-02T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 35, date_scanned: '2024-01-02T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);

    const { getByText, findByText } = renderWithProviders(<SummaryScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Total Money Spent')).toBeTruthy();
      expect(getByText('£200.00')).toBeTruthy();
      expect(getByText('Receipts Scanned')).toBeTruthy();
    });

    fireEvent.press(getByText('Your Spending Could Be Investing'));

    await findByText(/Instead of 3 receipts/i);
  });
});
