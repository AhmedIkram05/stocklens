import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';

import PortfolioDetailScreen from '@/screens/portfolio/PortfolioDetailScreen';
import { renderWithProviders } from '../../utils';
import { portfolioService } from '@/services/portfolios';
import { useNavigation, useRoute } from '@react-navigation/native';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    getPerformance: jest.fn(),
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
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

const mockPerformance = {
  portfolio_id: '1',
  portfolio_name: 'Test Portfolio',
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
  twr_methodology: 'daily_log_returns',
  free_cash_balance: 1000,
  data_quality: 'complete',
  holdings: [
    {
      ticker: 'AAPL',
      shares: 10,
      average_cost_basis: 150,
      current_price: 180,
      cost_basis: 1500,
      market_value: 1800,
      unrealised_pl: 300,
      unrealised_pl_pct: 20,
      day_change: 5,
      day_change_pct: 2.8,
      portfolio_weight_pct: 12,
      currency: 'USD',
      id: 'h1',
      portfolio_id: '1',
    },
    {
      ticker: 'TSLA',
      shares: 5,
      average_cost_basis: 700,
      current_price: 750,
      cost_basis: 3500,
      market_value: 3750,
      unrealised_pl: 250,
      unrealised_pl_pct: 7.14,
      day_change: -10,
      day_change_pct: -1.3,
      portfolio_weight_pct: 25,
      currency: 'USD',
      id: 'h2',
      portfolio_id: '1',
    },
  ],
  total_holdings: 2,
  calculated_at: new Date().toISOString(),
};

describe('PortfolioDetailScreen', () => {
  let navigateSpy: jest.Mock;

  beforeEach(() => {
    jest.useRealTimers();
    jest.clearAllMocks();
    navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1', portfolioName: 'Test Portfolio' },
      key: 'PortfolioDetail',
      name: 'PortfolioDetail' as any,
    } as any);
    mockedPortfolioService.getPerformance.mockResolvedValue(mockPerformance);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('shows loading state initially', async () => {
    mockedPortfolioService.getPerformance.mockImplementation(() => new Promise(() => {}));

    const { queryByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(queryByText('Test Portfolio')).toBeNull();
  });

  it('renders portfolio name and total value when loaded', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Test Portfolio')).toBeTruthy();
      expect(getByText('£15,000.00')).toBeTruthy();
    });
  });

  it('renders metrics row (Day Change, Total P&L, TWR)', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Day Change')).toBeTruthy();
      expect(getByText('Total P&L')).toBeTruthy();
      expect(getByText('TWR')).toBeTruthy();
    });

    expect(getByText('£100.00 (+0.67%)')).toBeTruthy();
    expect(getByText('£5,000.00 (+50.00%)')).toBeTruthy();
    expect(getByText('+0.45%')).toBeTruthy();
  });

  it('renders holdings table with data', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Holdings (2)')).toBeTruthy();
      expect(getByText('AAPL')).toBeTruthy();
      expect(getByText('TSLA')).toBeTruthy();
    });
  });

  it('shows empty holdings state', async () => {
    mockedPortfolioService.getPerformance.mockResolvedValue({
      ...mockPerformance,
      holdings: [],
    });

    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('No holdings yet. Tap Buy to get started.')).toBeTruthy();
    });
  });

  it('shows warning banner for partial data quality', async () => {
    mockedPortfolioService.getPerformance.mockResolvedValue({
      ...mockPerformance,
      data_quality: 'partial',
    });

    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Some holdings lack price data — values are partial.')).toBeTruthy();
    });
  });

  it('renders action buttons (Deposit, Trade, Benchmark)', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Deposit')).toBeTruthy();
      expect(getByText('Trade')).toBeTruthy();
      expect(getByText('Benchmark')).toBeTruthy();
    });
  });

  it('Deposit button navigates to Deposit screen', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Test Portfolio')).toBeTruthy());

    fireEvent.press(getByText('Deposit'));

    expect(navigateSpy).toHaveBeenCalledWith('Deposit', { portfolioId: '1' });
  });

  it('Trade button navigates to Trade screen', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Test Portfolio')).toBeTruthy());

    fireEvent.press(getByText('Trade'));

    expect(navigateSpy).toHaveBeenCalledWith('Trade', { portfolioId: '1', mode: 'buy' });
  });

  it('Benchmark button navigates to Benchmark screen', async () => {
    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Test Portfolio')).toBeTruthy());

    fireEvent.press(getByText('Benchmark'));

    expect(navigateSpy).toHaveBeenCalledWith('Benchmark', { portfolioId: '1' });
  });

  it('handles error state with retry button', async () => {
    mockedPortfolioService.getPerformance.mockRejectedValue(new Error('Failed to load'));

    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(getByText('Failed to load')).toBeTruthy();
      expect(getByText('Retry')).toBeTruthy();
    });
  });

  it('retry button re-fetches performance', async () => {
    mockedPortfolioService.getPerformance.mockRejectedValueOnce(new Error('Failed to load'));

    const { getByText } = renderWithProviders(<PortfolioDetailScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => expect(getByText('Failed to load')).toBeTruthy());

    mockedPortfolioService.getPerformance.mockResolvedValueOnce(mockPerformance);
    fireEvent.press(getByText('Retry'));

    await waitFor(() => {
      expect(mockedPortfolioService.getPerformance).toHaveBeenCalledTimes(2);
      expect(getByText('Test Portfolio')).toBeTruthy();
    });
  });
});
