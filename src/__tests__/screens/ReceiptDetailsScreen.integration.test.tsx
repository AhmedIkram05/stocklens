/**
 * Tests for `ReceiptDetailsScreen` (integration).
 * Verifies projection rendering, year-selector interactions, deletion flow,
 * and event-bus notifications.
 */

import React from 'react';
import { Alert } from 'react-native';
import { act, fireEvent, waitFor } from '@testing-library/react-native';

import ReceiptDetailsScreen from '@/screens/ReceiptDetailsScreen';
import { renderWithProviders } from '../utils';
import { receiptService } from '@/services/dataService';
import { emit, subscribe } from '@/services/eventBus';
import { getHistoricalCAGRFromToday } from '@/services/projectionService';
import { useNavigation, useRoute } from '@react-navigation/native';

jest.mock('@/services/dataService', () => ({
  receiptService: {
    delete: jest.fn(),
  },
  PREFETCH_TICKERS: ['NVDA', 'AAPL', 'MSFT', 'TSLA', 'NKE', 'AMZN', 'GOOGL', 'META', 'JPM', 'UNH'],
}));

jest.mock('@/services/eventBus', () => ({
  subscribe: jest.fn(() => jest.fn()),
  emit: jest.fn(),
}));

jest.mock('@/services/projectionService', () => ({
  getHistoricalCAGRFromToday: jest.fn(),
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(),
    useRoute: jest.fn(),
  };
});

const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;
const mockedEmit = emit as jest.MockedFunction<typeof emit>;
const mockedSubscribe = subscribe as jest.MockedFunction<typeof subscribe>;
const mockedGetHistorical = getHistoricalCAGRFromToday as jest.MockedFunction<
  typeof getHistoricalCAGRFromToday
>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

let navigateSpy: jest.Mock;
let goBackSpy: jest.Mock;

const defaultRouteParams = {
  receiptId: 44,
  totalAmount: 250,
  date: '2024-02-10T12:00:00.000Z',
  image: undefined,
};

describe('ReceiptDetailsScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedReceiptService.delete.mockResolvedValue(undefined);
    mockedGetHistorical.mockResolvedValue(0.12);
    navigateSpy = jest.fn();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({
      navigate: navigateSpy,
      goBack: goBackSpy,
    } as any);
    mockedUseRoute.mockReturnValue({ params: defaultRouteParams } as any);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders projections and updates headers when year selectors change', async () => {
    const { getByText, getAllByText } = renderWithProviders(<ReceiptDetailsScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Your £250.00 could have been...')).toBeTruthy();
      expect(getByText('If invested 5 years ago')).toBeTruthy();
    });

    const yearOptions = getAllByText('3Y');
    fireEvent.press(yearOptions[0]);

    await waitFor(() => {
      expect(getByText('If invested 3 years ago')).toBeTruthy();
    });

    const futureOptions = getAllByText('10Y');
    fireEvent.press(futureOptions[1]);

    await waitFor(() => {
      expect(getByText('If invested today for 10 years')).toBeTruthy();
    });

    expect(mockedGetHistorical).toHaveBeenCalled();
    expect(mockedSubscribe).toHaveBeenCalledWith('historical-updated', expect.any(Function));
  });

  it('confirms deletion before calling receiptService and navigation', async () => {
    const alertSpy = jest.spyOn(Alert, 'alert');

    const { getByLabelText } = renderWithProviders(<ReceiptDetailsScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByLabelText('Delete receipt'));

    const confirmButtons = alertSpy.mock.calls[0][2];
    const destructiveButton = confirmButtons?.find((button) => button?.style === 'destructive');

    await act(async () => {
      await destructiveButton?.onPress?.();
    });

    expect(mockedReceiptService.delete).toHaveBeenCalledWith(44);
    expect(mockedEmit).toHaveBeenCalledWith('receipts-changed', { id: 44, action: 'deleted' });
    expect(navigateSpy).toHaveBeenCalledWith('MainTabs');

    // success toast
    expect(alertSpy).toHaveBeenCalledWith('Deleted', 'Receipt deleted');
  });
});
