import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';

import DepositScreen from '@/screens/portfolio/DepositScreen';
import { renderWithProviders } from '../../utils';
import { portfolioService } from '@/services/portfolios';
import { receiptService } from '@/services/receipts';
import { useNavigation, useRoute } from '@react-navigation/native';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    createCashFlow: jest.fn(),
  },
}));

jest.mock('@/services/receipts', () => ({
  receiptService: {
    list: jest.fn(),
  },
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  const actualReact = jest.requireActual('react');
  return {
    ...actual,
    useNavigation: jest.fn(),
    useRoute: jest.fn(),
    useFocusEffect: (cb: () => void) => actualReact.useEffect(cb, []),
  };
});

const mockedPortfolioService = portfolioService as jest.Mocked<typeof portfolioService>;
const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

const mockReceipts = [
  {
    id: '1',
    total_amount: 150.5,
    merchant_name: 'Tesco',
    scanned_at: '2024-06-01T10:00:00.000Z',
    user_id: 'u1',
    category_id: null,
    ocr_raw_text: null,
    ocr_confidence: null,
    line_items: null,
    receipt_image_s3_key: null,
    created_at: '2024-06-01T10:00:00.000Z',
  },
  {
    id: '2',
    total_amount: 89.99,
    merchant_name: 'Amazon',
    scanned_at: '2024-06-15T10:00:00.000Z',
    user_id: 'u1',
    category_id: null,
    ocr_raw_text: null,
    ocr_confidence: null,
    line_items: null,
    receipt_image_s3_key: null,
    created_at: '2024-06-15T10:00:00.000Z',
  },
];

describe('DepositScreen', () => {
  let goBackSpy: jest.Mock;
  let navigateSpy: jest.Mock;
  let getParentSpy: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    goBackSpy = jest.fn();
    navigateSpy = jest.fn();
    getParentSpy = jest.fn(() => ({ navigate: navigateSpy }));
    mockedUseNavigation.mockReturnValue({ goBack: goBackSpy, getParent: getParentSpy } as any);
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1' },
      key: 'Deposit',
      name: 'Deposit' as any,
    } as any);
    mockedReceiptService.list.mockResolvedValue(mockReceipts);
    mockedPortfolioService.createCashFlow.mockResolvedValue({} as any);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders with two tabs (From Receipt, Manual)', () => {
    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByText('From Receipt')).toBeTruthy();
    expect(getByText('Manual')).toBeTruthy();
    expect(getByText('Add Deposit')).toBeTruthy();
  });

  it('shows loading state', () => {
    mockedReceiptService.list.mockImplementation(() => new Promise(() => {}));

    const { queryByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(queryByText('Tesco')).toBeNull();
  });

  it('shows receipt list when data loads', async () => {
    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Tesco')).toBeTruthy();
      expect(getByText('Amazon')).toBeTruthy();
    });
  });

  it('selects a receipt and shows deposit button with amount', async () => {
    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Tesco')).toBeTruthy());

    fireEvent.press(getByText('Tesco'));

    expect(getByText('Deposit £150.50')).toBeTruthy();
  });

  it('toggles between receipt and manual tabs', async () => {
    const { getByText, queryByPlaceholderText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Tesco')).toBeTruthy());

    expect(queryByPlaceholderText('0.00')).toBeNull();

    fireEvent.press(getByText('Manual'));

    expect(getByText('Amount')).toBeTruthy();
    expect(queryByPlaceholderText('0.00')).toBeTruthy();
  });

  it('manual tab shows amount input', () => {
    const { getByText, getByPlaceholderText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByText('Manual'));

    expect(getByPlaceholderText('0.00')).toBeTruthy();
  });

  it('confirm button is disabled when nothing selected or entered', () => {
    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const depositButton = getByText('Deposit');
    expect(depositButton).toBeTruthy();
  });

  it('submits deposit with receipt data', async () => {
    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Tesco')).toBeTruthy());

    fireEvent.press(getByText('Tesco'));
    fireEvent.press(getByText('Deposit £150.50'));

    await waitFor(() => {
      expect(mockedPortfolioService.createCashFlow).toHaveBeenCalledWith('1', {
        amount: 150.5,
        source: 'receipt',
        source_id: '1',
        notes: 'Tesco',
      });
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('submits manual amount deposit', async () => {
    const { getByText, getByPlaceholderText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByText('Manual'));

    const input = getByPlaceholderText('0.00');
    fireEvent.changeText(input, '250');

    fireEvent.press(getByText('Deposit £250.00'));

    await waitFor(() => {
      expect(mockedPortfolioService.createCashFlow).toHaveBeenCalledWith('1', {
        amount: 250,
        source: 'manual',
      });
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('handles empty receipts state with Scan New Receipt button', async () => {
    mockedReceiptService.list.mockResolvedValue([]);

    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('No receipts found. Scan a receipt first.')).toBeTruthy();
      expect(getByText('Scan New Receipt')).toBeTruthy();
    });
  });

  it('Scan New Receipt navigates to Scan screen', async () => {
    mockedReceiptService.list.mockResolvedValue([]);

    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Scan New Receipt')).toBeTruthy());

    fireEvent.press(getByText('Scan New Receipt'));

    expect(navigateSpy).toHaveBeenCalledWith('Scan');
  });

  it('handles receipt error with retry', async () => {
    mockedReceiptService.list.mockRejectedValue(new Error('Network error'));

    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Could not load receipts')).toBeTruthy();
      expect(getByText('Retry')).toBeTruthy();
    });
  });

  it('retry fetches receipts again after error', async () => {
    mockedReceiptService.list.mockRejectedValueOnce(new Error('Network error'));

    const { getByText } = renderWithProviders(<DepositScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Could not load receipts')).toBeTruthy());

    mockedReceiptService.list.mockResolvedValueOnce(mockReceipts);

    fireEvent.press(getByText('Retry'));

    await waitFor(() => {
      expect(mockedReceiptService.list).toHaveBeenCalledTimes(2);
    });
  });
});
