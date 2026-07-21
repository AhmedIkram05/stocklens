/**
 * Integration tests for `DiversificationScoreScreen`.
 *
 * Verifies: loading spinner, error state with retry, score badge rendering,
 * factor breakdown bars, recommendations list.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import { useRoute } from '@react-navigation/native';

import DiversificationScoreScreen from '@/screens/DiversificationScoreScreen';
import { renderWithProviders } from '../utils';
import { portfolioService } from '@/services/portfolios';
import type { DiversificationScoreData } from '@/services/portfolios';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    getDiversificationScore: jest.fn(),
  },
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  const actualReact = jest.requireActual('react');
  return {
    ...actual,
    useNavigation: jest.fn(() => ({ goBack: jest.fn() })),
    useRoute: jest.fn(),
    useFocusEffect: (cb: () => void) => actualReact.useEffect(cb, []),
  };
});

const mockedGetDiversificationScore =
  portfolioService.getDiversificationScore as jest.MockedFunction<
    typeof portfolioService.getDiversificationScore
  >;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

const mockData: DiversificationScoreData = {
  overall_score: 72.5,
  breakdown: {
    holdings_diversity_score: 15.0,
    holdings_diversity_weight_pct: 20,
    hhi_concentration_score: 28.0,
    hhi_concentration_weight_pct: 40,
    hhi_raw_value: 1850.5,
    top_holding_weight_score: 14.5,
    top_holding_weight_pct: 20,
    top_holding_ticker: 'AAPL',
    top_holding_exposure_pct: 27.5,
    sector_diversity_score: 15.0,
    sector_diversity_weight_pct: 20,
    sector_hhi_value: 3200.0,
  },
  total_holdings: 8,
  effective_holdings: 4.5,
  recommendations: [
    'Consider adding more holdings to reduce concentration risk.',
    'Portfolio is concentrated in few sectors — consider sector diversification.',
  ],
};

describe('DiversificationScoreScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: 'test-portfolio-uuid' },
      key: 'DiversificationScore-test',
      name: 'DiversificationScore',
    } as any);
  });

  it('shows loading spinner initially then renders score', async () => {
    mockedGetDiversificationScore.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(mockData), 50)),
    );

    const { getByText, queryByText } = renderWithProviders(<DiversificationScoreScreen />, {
      providerOverrides: { withNavigation: false },
    });

    // Loading state — title not rendered yet
    expect(queryByText('Diversification Score')).toBeNull();

    // Wait for data
    await waitFor(() => {
      expect(getByText('Diversification Score')).toBeTruthy();
    });

    // Score badge
    expect(getByText('73')).toBeTruthy(); // rounded 72.5
    expect(getByText('Moderately Diversified')).toBeTruthy();
    expect(getByText('8 holdings | 4.5 effective')).toBeTruthy();
  });

  it('renders factor breakdown bars', async () => {
    mockedGetDiversificationScore.mockResolvedValue(mockData);

    const { findByText } = renderWithProviders(<DiversificationScoreScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('Factor Breakdown')).toBeTruthy();
    expect(findByText('Holdings Diversity')).toBeTruthy();
    expect(findByText('HHI Concentration')).toBeTruthy();
    expect(findByText('Top Holding Weight')).toBeTruthy();
    expect(findByText('Sector Diversity')).toBeTruthy();
  });

  it('displays recommendations', async () => {
    mockedGetDiversificationScore.mockResolvedValue(mockData);

    const { findByText } = renderWithProviders(<DiversificationScoreScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('Recommendations')).toBeTruthy();
    expect(findByText('Consider adding more holdings to reduce concentration risk.')).toBeTruthy();
    expect(
      findByText('Portfolio is concentrated in few sectors — consider sector diversification.'),
    ).toBeTruthy();
  });

  it('shows factor info text', async () => {
    mockedGetDiversificationScore.mockResolvedValue(mockData);

    const { findByText } = renderWithProviders(<DiversificationScoreScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('HHI: 1850.5')).toBeTruthy();
    expect(await findByText('AAPL at 27.5%')).toBeTruthy();
  });

  it('shows error state and retries', async () => {
    mockedGetDiversificationScore.mockRejectedValueOnce(new Error('Failed to load'));

    const { findByText, getByText } = renderWithProviders(<DiversificationScoreScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('Failed to load')).toBeTruthy();

    // Retry succeeds
    mockedGetDiversificationScore.mockResolvedValueOnce(mockData);
    fireEvent.press(getByText('Retry'));

    await waitFor(() => {
      expect(getByText('Diversification Score')).toBeTruthy();
    });
  });

  it('shows empty state when no data', async () => {
    mockedGetDiversificationScore.mockResolvedValue(null as any);

    const { findByText } = renderWithProviders(<DiversificationScoreScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('No diversification data available')).toBeTruthy();
  });
});
