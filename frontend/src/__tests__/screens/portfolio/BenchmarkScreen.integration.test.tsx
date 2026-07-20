import React from 'react';
import { act, fireEvent, waitFor } from '@testing-library/react-native';

import BenchmarkScreen from '@/screens/portfolio/BenchmarkScreen';
import { renderWithProviders } from '../../utils';
import { portfolioService } from '@/services/portfolios';
import { useRoute } from '@react-navigation/native';

const originalSetInterval = global.setInterval;
const originalClearInterval = global.clearInterval;

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    getBenchmark: jest.fn(),
  },
}));

jest.mock('react-native-svg', () => {
  const React = require('react');
  const { View, Text: RNText } = require('react-native');
  const MockSvg = ({ children, ...props }: any) =>
    React.createElement(View, { testID: 'svg-mock', ...props }, children);
  const MockPolyline = (props: any) =>
    React.createElement(View, { testID: 'svg-polyline', ...props });
  const MockLine = (props: any) => React.createElement(View, { testID: 'svg-line', ...props });
  const MockSvgText = ({ children, ...props }: any) =>
    React.createElement(RNText, { testID: 'svg-text', ...props }, children);
  return {
    __esModule: true,
    default: MockSvg,
    Svg: MockSvg,
    Polyline: MockPolyline,
    Line: MockLine,
    Text: MockSvgText,
  };
});

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
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

const mockBenchmarkData = {
  portfolio_id: '1',
  benchmark_ticker: 'SPY',
  portfolio_return: 12.5,
  benchmark_return: 8.3,
  excess_return_alpha: 4.2,
  tracking_error: 2.1,
  information_ratio: 2.0,
  period_start: '2024-01-01',
  period_end: '2024-12-31',
  methodology: 'daily_log_returns',
  daily_returns_count: 252,
  calculated_at: '2024-12-31T00:00:00.000Z',
  portfolio_cumulative_returns: [
    { date: '2024-01-01', value: 0.0 },
    { date: '2024-06-01', value: 0.06 },
    { date: '2024-12-31', value: 0.125 },
  ],
  benchmark_cumulative_returns: [
    { date: '2024-01-01', value: 0.0 },
    { date: '2024-06-01', value: 0.04 },
    { date: '2024-12-31', value: 0.083 },
  ],
};

const mockInsuffientCumulativeData = {
  ...mockBenchmarkData,
  // 2 entries both on same date ⇒ unique dates < 2 ⇒ chart shows "Insufficient data"
  portfolio_cumulative_returns: [
    { date: '2024-01-01', value: 0.0 },
    { date: '2024-01-01', value: 0.06 },
  ],
  benchmark_cumulative_returns: [
    { date: '2024-01-01', value: 0.0 },
    { date: '2024-01-01', value: 0.04 },
  ],
};

async function flushMicrotasks() {
  await act(() => Promise.resolve());
}

describe('BenchmarkScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.setInterval = jest.fn(() => 123) as any;
    global.clearInterval = jest.fn() as any;
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: '1', benchmarkTicker: 'SPY' },
      key: 'Benchmark',
      name: 'Benchmark' as any,
    } as any);
    mockedPortfolioService.getBenchmark.mockResolvedValue(mockBenchmarkData);
  });

  afterEach(() => {
    global.setInterval = originalSetInterval;
    global.clearInterval = originalClearInterval;
    jest.restoreAllMocks();
  });

  it('renders loading state initially', async () => {
    mockedPortfolioService.getBenchmark.mockImplementation(() => new Promise(() => {}));

    const { getByText, queryByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByText('Benchmark')).toBeTruthy();
    expect(getByText('Loading...')).toBeTruthy();
    expect(queryByText('Alpha')).toBeNull();
  });

  it('renders benchmark data when loaded', async () => {
    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();

    expect(mockedPortfolioService.getBenchmark).toHaveBeenCalledWith(
      '1',
      'SPY',
      expect.any(String),
    );
    expect(getByText('Alpha')).toBeTruthy();
    expect(getByText('+4.20%')).toBeTruthy();
    expect(getByText('Tracking Error')).toBeTruthy();
    expect(getByText('2.10%')).toBeTruthy();
    expect(getByText('Info Ratio')).toBeTruthy();
    expect(getByText('2.00')).toBeTruthy();
  });

  it('shows portfolio return and benchmark return', async () => {
    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();

    expect(getByText('12.50%')).toBeTruthy();
    expect(getByText('8.30%')).toBeTruthy();
  });

  it('shows empty chart state when insufficient data', async () => {
    mockedPortfolioService.getBenchmark.mockResolvedValue(mockInsuffientCumulativeData);

    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();

    expect(getByText('Insufficient data for chart')).toBeTruthy();
  });

  it('renders chart when cumulative return data exists', async () => {
    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();

    expect(getByText('Cumulative Return — 1 year')).toBeTruthy();
  });

  it('toggles benchmark ticker buttons (SPY/QQQ)', async () => {
    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();
    expect(getByText('+4.20%')).toBeTruthy();

    fireEvent.press(getByText('QQQ'));

    await waitFor(() => {
      expect(mockedPortfolioService.getBenchmark).toHaveBeenCalledWith(
        '1',
        'QQQ',
        expect.any(String),
      );
    });
  });

  it('changes period via YearSelector', async () => {
    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();
    expect(getByText('+4.20%')).toBeTruthy();

    fireEvent.press(getByText('3Y'));

    await waitFor(() => {
      expect(mockedPortfolioService.getBenchmark).toHaveBeenCalledWith(
        '1',
        'SPY',
        expect.any(String),
      );
    });
  });

  it('handles API error gracefully keeping stale data', async () => {
    const { getByText } = renderWithProviders(<BenchmarkScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await flushMicrotasks();
    expect(getByText('+4.20%')).toBeTruthy();

    mockedPortfolioService.getBenchmark.mockRejectedValue(new Error('Network error'));

    fireEvent.press(getByText('QQQ'));

    await waitFor(() => {
      expect(getByText('+4.20%')).toBeTruthy();
    });
  });
});
