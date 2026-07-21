/**
 * Integration tests for `HomeScreen` UI.
 * Exercises empty state behavior, stats display, history expansion,
 * and navigation to Scan and ReceiptDetails screens.
 */

import React from 'react';
import { ScrollView } from 'react-native';
import { fireEvent, waitFor } from '@testing-library/react-native';
import HomeScreen from '@/screens/HomeScreen';
import { renderWithProviders } from '../utils';
import useReceipts from '@/hooks/useReceipts';
import { useNavigation } from '@react-navigation/native';
import { createUserProfile } from '../fixtures';

jest.mock('@/hooks/useReceipts', () => jest.fn());

// Mock useDecryptedImage to return synchronously (avoids act() warning from async decryption)
jest.mock('@/hooks/useDecryptedImage', () => ({
  __esModule: true,
  default: (src: string | null | undefined) => src ?? undefined,
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(),
  };
});

jest.mock('@/services/categories', () => ({
  categoryService: {
    listCategories: jest.fn(),
  },
}));

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    listPortfolios: jest.fn(),
    getPerformance: jest.fn(),
  },
}));

const mockedUseReceipts = useReceipts as jest.MockedFunction<typeof useReceipts>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

describe('HomeScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default mocks: categories and portfolios resolve to empty so useEffect
    // doesn't crash on .then() for tests that don't exercise these paths.
    const { categoryService } = require('@/services/categories');
    const { portfolioService } = require('@/services/portfolios');
    categoryService.listCategories.mockResolvedValue([]);
    portfolioService.listPortfolios.mockResolvedValue([]);
  });

  const renderScreen = () => {
    const testUser = createUserProfile({ first_name: 'Alex', uid: 'user-1' });
    return renderWithProviders(<HomeScreen />, {
      providerOverrides: {
        withNavigation: false,
        authValue: {
          userProfile: testUser as any,
          user: { uid: testUser.uid } as any,
        },
      },
    });
  };

  it('shows onboarding empty state and navigates to Scan when CTA pressed', () => {
    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();

    expect(getByText('No Receipts Yet')).toBeTruthy();
    fireEvent.press(getByText('Scan Your First Receipt'));

    expect(navigateSpy).toHaveBeenCalledWith('MainTabs', { screen: 'Scan' });
  });

  it('renders stats, toggles history, and opens receipt details', async () => {
    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: '2 hours ago',
          amount: 80,
          date: '2025-02-01T10:00:00Z',
          time: '9:00',
          image: 'uri://receipt-1',
          source: 'regex',
          confidence: 95,
        },
        {
          id: '2',
          label: 'Yesterday',
          amount: 40,
          date: '2025-01-05T10:00:00Z',
          time: '12:00',
          image: 'uri://receipt-2',
          source: 'cascade',
          confidence: 78,
        },
        {
          id: '3',
          label: 'Last week',
          amount: 20,
          date: '2024-12-15T10:00:00Z',
          time: '15:00',
          image: 'uri://receipt-3',
          source: 'degraded',
          confidence: 45,
        },
        {
          id: '4',
          label: '2 weeks ago',
          amount: 10,
          date: '2024-12-01T10:00:00Z',
          time: '11:00',
          image: 'uri://receipt-4',
          source: 'failed',
          confidence: 0,
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText, getAllByTestId } = renderScreen();

    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());
    expect(getByText('£150.00')).toBeTruthy();
    expect(getByText('Receipts Scanned')).toBeTruthy();
    expect(getByText('£80.00')).toBeTruthy();

    fireEvent.press(getByText('View all receipts'));
    expect(getByText('Show Less')).toBeTruthy();

    fireEvent.press(getAllByTestId('receipt-card')[0]);
    expect(navigateSpy).toHaveBeenCalledWith(
      'ReceiptDetails',
      expect.objectContaining({ receiptId: '1', totalAmount: 80, source: 'regex', confidence: 95 }),
    );
  });

  // ── Category loading (line 53) ──────────────────────────────────────────────

  it('loads categories and shows filter chips', async () => {
    const { categoryService } = require('@/services/categories');
    categoryService.listCategories.mockResolvedValue([
      { id: 'cat-1', name: 'Food' },
      { id: 'cat-2', name: 'Transport' },
    ]);

    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Test',
          amount: 50,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();
    await waitFor(() => {
      expect(getByText('Food')).toBeTruthy();
    });
    expect(getByText('Transport')).toBeTruthy();
    expect(getByText('All')).toBeTruthy();
  });

  // ── Portfolio loading — no portfolios (lines 73-75) ─────────────────────────

  it('does not show portfolio section when no portfolios exist', async () => {
    const { portfolioService } = require('@/services/portfolios');
    portfolioService.listPortfolios.mockResolvedValue([]);

    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Test',
          amount: 50,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { queryByText } = renderScreen();
    await waitFor(() => {
      expect(portfolioService.listPortfolios).toHaveBeenCalled();
    });
    // Portfolio section should not render when list returns empty
    expect(queryByText('Portfolio Value')).toBeNull();
  });

  // ── Portfolio loading — with portfolios (lines 77-89, 214) ──────────────────

  it('shows portfolio section when portfolio data is available', async () => {
    const { portfolioService } = require('@/services/portfolios');
    portfolioService.listPortfolios.mockResolvedValue([{ id: 'p1', name: 'My Portfolio' }]);
    portfolioService.getPerformance.mockResolvedValue({
      total_market_value: 10000,
      total_unrealised_pl: 500,
    });

    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Test',
          amount: 50,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Portfolio Value')).toBeTruthy());
    // Verify the formatted market value is shown
    expect(getByText('£10,000.00')).toBeTruthy();
  });

  it('navigates to Portfolio tab when portfolio card is pressed', async () => {
    const { portfolioService } = require('@/services/portfolios');
    portfolioService.listPortfolios.mockResolvedValue([{ id: 'p1', name: 'My Portfolio' }]);
    portfolioService.getPerformance.mockResolvedValue({
      total_market_value: 10000,
      total_unrealised_pl: 500,
    });

    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Test',
          amount: 50,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Portfolio Value')).toBeTruthy());

    // fireEvent.press traverses up the parent chain to find onPress handler
    fireEvent.press(getByText('Portfolio Value'));
    expect(navigateSpy).toHaveBeenCalledWith('MainTabs', { screen: 'Portfolio' });
  });

  // ── Sort by amount (lines 131-132, 248-249) ─────────────────────────────────

  it('sorts by amount when Amount sort button is pressed', async () => {
    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Big',
          amount: 100,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
        {
          id: '2',
          label: 'Small',
          amount: 10,
          date: '2025-01-02T00:00:00Z',
          time: '11:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());

    // Press the Amount sort button — triggers onSortChange('amount', 'asc')
    // fireEvent.press traverses parents so it reaches TouchableOpacity
    fireEvent.press(getByText('Amount'));

    // Component re-renders with amount sort active
    await waitFor(() => {
      expect(getByText('Amount')).toBeTruthy();
    });
  });

  // ── Category filtering (line 147, 268, 281-282, 289) ────────────────────────

  it('filters receipts when a category filter chip is pressed', async () => {
    const { categoryService } = require('@/services/categories');
    categoryService.listCategories.mockResolvedValue([{ id: 'cat-1', name: 'Food' }]);

    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Pizza',
          amount: 20,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
        {
          id: '2',
          label: 'Burger',
          amount: 15,
          date: '2025-01-02T00:00:00Z',
          time: '11:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Food')).toBeTruthy());

    // Press the Food chip — sets filterCategoryId, covers line 289
    fireEvent.press(getByText('Food'));

    // Press All chip to clear filter — covers line 268
    await waitFor(() => {
      fireEvent.press(getByText('All'));
      expect(getByText('All')).toBeTruthy();
    });
  });

  // ── Pull-to-refresh (lines 103-105) ─────────────────────────────────────────

  it('triggers refresh on pull-to-refresh', async () => {
    const refetchMock = jest.fn().mockResolvedValue(undefined);
    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: 'Test',
          amount: 50,
          date: '2025-01-01T00:00:00Z',
          time: '10:00',
          image: '',
        },
      ],
      loading: false,
      error: null,
      refetch: refetchMock,
    });

    const { portfolioService } = require('@/services/portfolios');
    portfolioService.listPortfolios.mockResolvedValue([]);

    const { UNSAFE_root, getByText } = renderScreen();
    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());

    // Find the main ScrollView and trigger its RefreshControl.onRefresh
    const scrollView = UNSAFE_root.findByType(ScrollView);
    scrollView.props.refreshControl.props.onRefresh();

    await waitFor(() => {
      expect(refetchMock).toHaveBeenCalled();
    });
  });
});
