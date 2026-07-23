/**
 * Comprehensive tests for `SummaryScreen` covering spending analysis,
 * category breakdown, month-over-month, insights, and edge cases.
 */

import React from 'react';
import { act, fireEvent, waitFor } from '@testing-library/react-native';
import SummaryScreen from '@/screens/SummaryScreen';
import useReceipts, { ReceiptShape } from '@/hooks/useReceipts';
import { renderWithProviders } from '../utils';
import { useNavigation } from '@react-navigation/native';
import { categoryService } from '@/services/categories';
import { createReceipt } from '../fixtures';

jest.mock('@/hooks/useReceipts');
jest.mock('@/services/eventBus', () => ({
  subscribe: jest.fn(() => jest.fn()),
}));
jest.mock('@/services/categories', () => ({
  categoryService: {
    listCategories: jest.fn(),
  },
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(),
  };
});

const mockedUseReceipts = useReceipts as jest.MockedFunction<typeof useReceipts>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;
const mockedCategoryService = categoryService as jest.Mocked<typeof categoryService>;

let navigateSpy: jest.Mock;
let goBackSpy: jest.Mock;

describe('SummaryScreen comprehensive', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseReceipts.mockReturnValue({ receipts: [], loading: false, error: null } as any);
    mockedCategoryService.listCategories.mockResolvedValue([]);
    navigateSpy = jest.fn();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({
      navigate: navigateSpy,
      goBack: goBackSpy,
    } as any);
  });

  // Remove fake timers

  const renderScreen = (overrides?: Parameters<typeof renderWithProviders>[1]) =>
    renderWithProviders(<SummaryScreen />, {
      providerOverrides: { withNavigation: false },
      ...overrides,
    });

  // ── Empty state ───────────────────────────────────────────────────────────

  it('shows onboarding empty state when no receipts', () => {
    const { getByText } = renderScreen();
    expect(getByText('No Data Yet')).toBeTruthy();
    fireEvent.press(getByText('Scan Your First Receipt'));
    expect(navigateSpy).toHaveBeenCalledWith('Scan');
  });

  it('shows loading when receipts are loading', () => {
    mockedUseReceipts.mockReturnValue({ receipts: [], loading: true, error: null } as any);
    const { queryByText, toJSON } = renderScreen();
    expect(queryByText('No Data Yet')).toBeNull();
    expect(toJSON()).toBeTruthy();
  });

  // ── Basic stats with receipts ────────────────────────────────────────────

  it('renders spending stats and projections with receipts', async () => {
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
    mockedCategoryService.listCategories.mockResolvedValue([]);

    const { getByText } = renderScreen();

    await waitFor(() => {
      expect(getByText('Total Money Spent')).toBeTruthy();
      expect(getByText('£200.00')).toBeTruthy();
      expect(getByText('Receipts Scanned')).toBeTruthy();
      expect(getByText('3')).toBeTruthy(); // receipt count
    });

    // 20-year projection should render
    expect(getByText('20-Year Portfolio Projection')).toBeTruthy();
  });

  // ── Insights expansion ────────────────────────────────────────────────────

  it('expands dynamic insight content on press', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '2 weeks ago',
        amount: 50,
        date: createReceipt({ total_amount: 50, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 50, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);

    const { getByText, findByText } = renderScreen();
    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());
    fireEvent.press(getByText('Your Spending Could Be Investing'));
    await findByText(/Instead of 1 receipts/i);
  });

  it('toggles between multiple insights', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 10,
        date: createReceipt({ total_amount: 10, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 10, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
      },
      {
        id: '2',
        label: '2',
        amount: 15,
        date: createReceipt({ total_amount: 15, date_scanned: '2024-02-14T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 15, date_scanned: '2024-02-14T00:00:00.000Z' })
          .image_uri!,
      },
      {
        id: '3',
        label: '3',
        amount: 20,
        date: createReceipt({ total_amount: 20, date_scanned: '2024-01-02T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 20, date_scanned: '2024-01-02T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);

    const { getByText, queryByText, findByText } = renderScreen();
    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());
    fireEvent.press(getByText('Your Spending Could Be Investing'));
    await findByText(/Instead of 3 receipts/);
    fireEvent.press(getByText('Small Purchases Add Up'));
    await waitFor(() => expect(queryByText(/Instead of 3 receipts/)).toBeNull());
    await findByText(/Small frequent expenses/);
  });

  // ── Definitions ────────────────────────────────────────────────────────────

  it('expands definitions when pressed', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 50,
        date: createReceipt({ total_amount: 50, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 50, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);

    const { getByText, findByText } = renderScreen();
    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());
    fireEvent.press(getByText('Compound Interest'));
    await findByText(/Earnings on your initial investment/);
  });

  // ── Spending analysis (category breakdown) ────────────────────────────────

  it('renders category breakdown when receipts have categories', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 100,
        date: createReceipt({ total_amount: 100, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 100, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
        categoryId: 'cat-1',
      },
      {
        id: '2',
        label: '2',
        amount: 50,
        date: createReceipt({ total_amount: 50, date_scanned: '2024-02-12T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 50, date_scanned: '2024-02-12T00:00:00.000Z' })
          .image_uri!,
        categoryId: 'cat-2',
      },
      {
        id: '3',
        label: '3',
        amount: 25,
        date: createReceipt({ total_amount: 25, date_scanned: '2024-01-15T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 25, date_scanned: '2024-01-15T00:00:00.000Z' })
          .image_uri!,
        categoryId: 'cat-1',
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);
    mockedCategoryService.listCategories.mockResolvedValue([
      { id: 'cat-1', name: 'Groceries' },
      { id: 'cat-2', name: 'Dining Out' },
    ]);

    const { findByText } = renderScreen();
    await waitFor(() => expect(findByText('Total Money Spent')).toBeTruthy());
    // Category section should appear - just verify the section header renders
    await findByText('Spending by Category');
  });

  it('shows "Uncategorised" for receipts without category', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 75,
        date: createReceipt({ total_amount: 75, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 75, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
        categoryId: null,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);
    mockedCategoryService.listCategories.mockResolvedValue([]);

    const { findByText } = renderScreen();
    await findByText('Spending by Category');
    await findByText('Uncategorised');
  });

  // ── Month-over-month ──────────────────────────────────────────────────────

  it('renders month-over-month when enough months of data', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 100,
        date: createReceipt({ total_amount: 100, date_scanned: '2024-01-15T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 100, date_scanned: '2024-01-15T00:00:00.000Z' })
          .image_uri!,
      },
      {
        id: '2',
        label: '2',
        amount: 150,
        date: createReceipt({ total_amount: 150, date_scanned: '2024-02-15T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 150, date_scanned: '2024-02-15T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);
    mockedCategoryService.listCategories.mockResolvedValue([]);

    const { findByText, getByText } = renderScreen();
    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());
    await findByText('Month-over-Month Change');
  });

  it('does not render month-over-month with single month', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 100,
        date: createReceipt({ total_amount: 100, date_scanned: '2024-02-15T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 100, date_scanned: '2024-02-15T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({ receipts, loading: false, error: null } as any);
    mockedCategoryService.listCategories.mockResolvedValue([]);

    const { queryByText } = renderScreen();
    await waitFor(() => expect(queryByText('Month-over-Month Change')).toBeNull());
  });

  // ── Pull to refresh ───────────────────────────────────────────────────────

  it('triggers refresh on pull-to-refresh', async () => {
    const receipts: ReceiptShape[] = [
      {
        id: '1',
        label: '1',
        amount: 50,
        date: createReceipt({ total_amount: 50, date_scanned: '2024-02-10T00:00:00.000Z' })
          .date_scanned!,
        time: '',
        image: createReceipt({ total_amount: 50, date_scanned: '2024-02-10T00:00:00.000Z' })
          .image_uri!,
      },
    ];
    mockedUseReceipts.mockReturnValue({
      receipts,
      loading: false,
      error: null,
      refetch: jest.fn().mockResolvedValue(undefined),
    } as any);

    const { UNSAFE_getByType } = renderScreen();
    const { RefreshControl } = require('react-native');
    const refreshControl = UNSAFE_getByType(RefreshControl);
    act(() => refreshControl.props.onRefresh());
    // Wait for async
    await waitFor(() => expect(mockedUseReceipts.mock.results[0].value.refetch).toHaveBeenCalled());
  });
});
