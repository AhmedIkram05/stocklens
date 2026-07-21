/**
 * Tests for `PortfolioListScreen` (integration).
 * Verifies loading, empty, data, error states, and navigation.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';

import PortfolioListScreen from '@/screens/portfolio/PortfolioListScreen';
import { renderWithProviders } from '../../utils';
import { portfolioService } from '@/services/portfolios';
import { useNavigation } from '@react-navigation/native';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    listPortfolios: jest.fn(),
    getPerformance: jest.fn(),
  },
}));

jest.mock('@/services/market', () => ({}));

jest.mock('@/screens/AgentChatScreen', () => () => null);

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
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

const mockPortfolios = [
  {
    id: '1',
    name: 'Growth Fund',
    created_at: '2024-01-01T00:00:00.000Z',
    updated_at: '2024-06-01T00:00:00.000Z',
  },
  {
    id: '2',
    name: 'Dividend Portfolio',
    created_at: '2024-02-01T00:00:00.000Z',
    updated_at: '2024-06-15T00:00:00.000Z',
  },
];

const mockPerformance = {
  portfolio_id: '1',
  portfolio_name: 'Growth Fund',
  total_market_value: 15000,
  total_cost_basis: 10000,
  total_unrealised_pl: 5000,
  total_unrealised_pl_pct: 50,
  day_change: 100,
  day_change_pct: 0.67,
  twr: 0.45,
  twr_annualised: 0.22,
  twr_start_date: null,
  twr_end_date: null,
  twr_methodology: '',
  free_cash_balance: 1000,
  data_quality: 'complete',
  holdings: [],
  total_holdings: 0,
  calculated_at: new Date().toISOString(),
};

describe('PortfolioListScreen', () => {
  let navigateSpy: jest.Mock;

  beforeEach(() => {
    jest.useRealTimers();
    jest.clearAllMocks();
    navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedPortfolioService.listPortfolios.mockResolvedValue(mockPortfolios);
    mockedPortfolioService.getPerformance.mockResolvedValue(mockPerformance);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders loading state initially', async () => {
    mockedPortfolioService.listPortfolios.mockImplementation(() => new Promise(() => {}));

    const { getByText, queryByText } = renderWithProviders(<PortfolioListScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByText('My Portfolios')).toBeTruthy();
    expect(queryByText('Growth Fund')).toBeNull();
  });

  it('shows "No portfolios yet" when list returns empty', async () => {
    mockedPortfolioService.listPortfolios.mockResolvedValue([]);

    const { getByText } = renderWithProviders(<PortfolioListScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(
      () => {
        expect(getByText('No portfolios yet.')).toBeTruthy();
      },
      { timeout: 8000 },
    );
  });

  it('renders portfolio cards when data loads', async () => {
    const { getByText, getAllByText } = renderWithProviders(<PortfolioListScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Growth Fund')).toBeTruthy();
      expect(getByText('Dividend Portfolio')).toBeTruthy();
    });

    expect(getAllByText('£15,000.00')).toHaveLength(2);
    expect(getAllByText('£5,000.00')).toHaveLength(2);
    expect(getAllByText('+50.00%')).toHaveLength(2);
  });

  it('navigates to CreatePortfolio when "+" is pressed', async () => {
    const { getByText } = renderWithProviders(<PortfolioListScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Growth Fund')).toBeTruthy());

    fireEvent.press(getByText('+'));

    expect(navigateSpy).toHaveBeenCalledWith('CreatePortfolio');
  });

  it('navigates to PortfolioDetail with correct params when card is pressed', async () => {
    const { getByText } = renderWithProviders(<PortfolioListScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Growth Fund')).toBeTruthy());

    fireEvent.press(getByText('Growth Fund'));

    expect(navigateSpy).toHaveBeenCalledWith('PortfolioDetail', {
      portfolioId: '1',
      portfolioName: 'Growth Fund',
    });
  });

  it('shows error state when API fails', async () => {
    mockedPortfolioService.listPortfolios.mockRejectedValue(new Error('Network error'));

    const { getByText } = renderWithProviders(<PortfolioListScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Failed to load portfolios')).toBeTruthy();
    });
  });
});
