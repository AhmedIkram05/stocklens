import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';

import TradeScreen from '@/screens/portfolio/TradeScreen';
import { renderWithProviders } from '../../utils';
import { portfolioService } from '@/services/portfolios';
import { marketService } from '@/services/market';
import { useNavigation, useRoute } from '@react-navigation/native';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    listHoldings: jest.fn(),
    createTransaction: jest.fn(),
  },
}));

jest.mock('@/services/market', () => ({
  marketService: {
    getQuote: jest.fn(),
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
const mockedMarketService = marketService as jest.Mocked<typeof marketService>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

const mockQuote = {
  ticker: 'AAPL',
  price: 180.5,
  change: 2.5,
  change_pct: 1.4,
  previous_close: 178,
  volume: 50000000,
  timestamp: '2024-06-01T10:00:00.000Z',
  currency: 'USD',
};

const mockHoldings = [
  {
    id: 'h1',
    portfolio_id: '1',
    ticker: 'AAPL',
    shares: 10,
    average_cost_basis: 150,
    currency: 'USD',
    average_cost_basis_gbp: 120,
    created_at: '2024-01-01T00:00:00.000Z',
    updated_at: '2024-06-01T00:00:00.000Z',
  },
  {
    id: 'h2',
    portfolio_id: '1',
    ticker: 'TSLA',
    shares: 5,
    average_cost_basis: 700,
    currency: 'USD',
    average_cost_basis_gbp: 560,
    created_at: '2024-02-01T00:00:00.000Z',
    updated_at: '2024-06-01T00:00:00.000Z',
  },
];

describe('TradeScreen', () => {
  let goBackSpy: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ goBack: goBackSpy } as any);
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1', mode: 'buy' },
      key: 'Trade',
      name: 'Trade' as any,
    } as any);
    mockedMarketService.getQuote.mockResolvedValue(mockQuote);
    mockedPortfolioService.listHoldings.mockResolvedValue(mockHoldings);
    mockedPortfolioService.createTransaction.mockResolvedValue({} as any);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders trade form with ticker and shares inputs', () => {
    const { getByPlaceholderText, getAllByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getAllByText('Buy').length).toBeGreaterThanOrEqual(1);
    expect(getByPlaceholderText('AAPL')).toBeTruthy();
    expect(getByPlaceholderText('0')).toBeTruthy();
  });

  it('shows buy/sell mode toggle', () => {
    const { getAllByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getAllByText('Buy').length).toBeGreaterThanOrEqual(1);
    expect(getAllByText('Sell').length).toBeGreaterThanOrEqual(1);
  });

  it('looks up quote when ticker is entered', async () => {
    const { getByPlaceholderText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'AAPL');
    fireEvent(tickerInput, 'blur');

    await waitFor(() => {
      expect(mockedMarketService.getQuote).toHaveBeenCalledWith('AAPL');
    });
  });

  it('shows quote preview after ticker lookup', async () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'AAPL');
    fireEvent(tickerInput, 'blur');

    const sharesInput = getByPlaceholderText('0');
    fireEvent.changeText(sharesInput, '10');

    await waitFor(() => {
      expect(getByText(/AAPL/)).toBeTruthy();
    });
  });

  it('shows quote error state', async () => {
    mockedMarketService.getQuote.mockRejectedValue(new Error('Symbol not found'));

    const { getByPlaceholderText, getByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'INVALID');
    fireEvent(tickerInput, 'blur');

    await waitFor(() => {
      expect(getByText('Could not fetch quote')).toBeTruthy();
    });
  });

  it('shows holdings when in sell mode', async () => {
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1', mode: 'sell' },
      key: 'Trade',
      name: 'Trade' as any,
    } as any);

    renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(mockedPortfolioService.listHoldings).toHaveBeenCalledWith('1');
    });
  });

  it('submits buy order', async () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'AAPL');
    fireEvent(tickerInput, 'blur');

    await waitFor(() => expect(mockedMarketService.getQuote).toHaveBeenCalled());

    const sharesInput = getByPlaceholderText('0');
    fireEvent.changeText(sharesInput, '10');

    const confirmButton = getByText('Buy US$1,805.00');
    fireEvent.press(confirmButton);

    await waitFor(() => {
      expect(mockedPortfolioService.createTransaction).toHaveBeenCalledWith('1', {
        ticker: 'AAPL',
        shares: 10,
        price_per_share: 180.5,
        type: 'BUY',
      });
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('submits sell order', async () => {
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1', mode: 'sell' },
      key: 'Trade',
      name: 'Trade' as any,
    } as any);

    const { getByPlaceholderText, getByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(mockedPortfolioService.listHoldings).toHaveBeenCalledWith('1');
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'AAPL');
    fireEvent(tickerInput, 'blur');

    await waitFor(() => expect(mockedMarketService.getQuote).toHaveBeenCalled());

    const sharesInput = getByPlaceholderText('0');
    fireEvent.changeText(sharesInput, '5');

    const confirmButton = getByText(' Sell US$902.50');
    fireEvent.press(confirmButton);

    await waitFor(() => {
      expect(mockedPortfolioService.createTransaction).toHaveBeenCalledWith('1', {
        ticker: 'AAPL',
        shares: 5,
        price_per_share: 180.5,
        type: 'SELL',
      });
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('validates sell does not exceed holdings', async () => {
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1', mode: 'sell' },
      key: 'Trade',
      name: 'Trade' as any,
    } as any);

    const { getByPlaceholderText, getByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await waitFor(() => {
      expect(mockedPortfolioService.listHoldings).toHaveBeenCalledWith('1');
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'AAPL');
    fireEvent(tickerInput, 'blur');

    await waitFor(() => expect(mockedMarketService.getQuote).toHaveBeenCalled());

    const sharesInput = getByPlaceholderText('0');
    fireEvent.changeText(sharesInput, '20');

    await waitFor(() => {
      expect(getByText('You only own 10 shares of AAPL')).toBeTruthy();
    });
  });

  it('handles submit error', async () => {
    mockedPortfolioService.createTransaction.mockRejectedValue(new Error('Insufficient funds'));

    const { getByPlaceholderText, getByText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const tickerInput = getByPlaceholderText('AAPL');
    fireEvent.changeText(tickerInput, 'AAPL');
    fireEvent(tickerInput, 'blur');

    await waitFor(() => expect(mockedMarketService.getQuote).toHaveBeenCalled());

    const sharesInput = getByPlaceholderText('0');
    fireEvent.changeText(sharesInput, '10');

    const confirmButton = getByText('Buy US$1,805.00');
    fireEvent.press(confirmButton);

    await waitFor(() => {
      expect(getByText('Transaction failed')).toBeTruthy();
    });
  });

  it('back button calls navigation.goBack', () => {
    const { getByLabelText } = renderWithProviders(<TradeScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByLabelText('Go back'));

    expect(goBackSpy).toHaveBeenCalled();
  });
});
