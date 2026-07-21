/**
 * Integration tests for `SectorExposureScreen`.
 *
 * Verifies: loading spinner, error state with retry, empty state,
 * sector bars rendering, total value display, and tap-to-expand ticker list.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import { useRoute } from '@react-navigation/native';

import SectorExposureScreen from '@/screens/SectorExposureScreen';
import { renderWithProviders } from '../utils';
import { portfolioService } from '@/services/portfolios';
import type { SectorExposureData } from '@/services/portfolios';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    getSectorExposure: jest.fn(),
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

const mockedGetSectorExposure = portfolioService.getSectorExposure as jest.MockedFunction<
  typeof portfolioService.getSectorExposure
>;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

const mockData: SectorExposureData = {
  total_value_gbp: 50000,
  sectors: [
    {
      sector: 'Technology',
      value_gbp: 20000,
      allocation_pct: 40,
      tickers: ['AAPL', 'MSFT', 'GOOGL'],
    },
    {
      sector: 'Healthcare',
      value_gbp: 15000,
      allocation_pct: 30,
      tickers: ['JNJ', 'PFE'],
    },
    {
      sector: 'Finance',
      value_gbp: 15000,
      allocation_pct: 30,
      tickers: ['JPM', 'GS'],
    },
  ],
};

describe('SectorExposureScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseRoute.mockReturnValue({
      params: { portfolioId: 'test-portfolio-uuid' },
      key: 'SectorExposure-test',
      name: 'SectorExposure',
    } as any);
  });

  it('shows loading spinner initially and then renders sectors', async () => {
    mockedGetSectorExposure.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(mockData), 50)),
    );

    const { getByText, queryByText } = renderWithProviders(<SectorExposureScreen />, {
      providerOverrides: { withNavigation: false },
    });

    // Loading state
    expect(queryByText('Sector Exposure')).toBeNull();

    // Wait for data
    await waitFor(() => {
      expect(getByText('Sector Exposure')).toBeTruthy();
    });

    expect(getByText('Total Portfolio Value')).toBeTruthy();
    expect(getByText('£50,000.00')).toBeTruthy();
    expect(getByText('Technology')).toBeTruthy();
    expect(getByText('Healthcare')).toBeTruthy();
    expect(getByText('Finance')).toBeTruthy();
  });

  it('renders sector percentages correctly', async () => {
    mockedGetSectorExposure.mockResolvedValue(mockData);

    const { findByText, findAllByText } = renderWithProviders(<SectorExposureScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('40.0%')).toBeTruthy();
    const pcts = await findAllByText('30.0%');
    expect(pcts).toHaveLength(2);
  });

  it('shows ticker list when sector is tapped', async () => {
    mockedGetSectorExposure.mockResolvedValue(mockData);

    const { findByText, getByText } = renderWithProviders(<SectorExposureScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await findByText('Technology');

    fireEvent.press(getByText('Technology'));

    expect(getByText('Holdings')).toBeTruthy();
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('MSFT')).toBeTruthy();
    expect(getByText('GOOGL')).toBeTruthy();
  });

  it('shows error state and retries', async () => {
    mockedGetSectorExposure.mockRejectedValue(new Error('API error'));
    mockedGetSectorExposure.mockClear();

    // First call fails
    mockedGetSectorExposure.mockRejectedValueOnce(new Error('API error'));

    const { findByText, getByText } = renderWithProviders(<SectorExposureScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('API error')).toBeTruthy();

    // Second call succeeds on retry
    mockedGetSectorExposure.mockResolvedValueOnce(mockData);
    fireEvent.press(getByText('Retry'));

    await waitFor(() => {
      expect(getByText('Technology')).toBeTruthy();
    });
  });

  it('shows empty state when no sectors returned', async () => {
    mockedGetSectorExposure.mockResolvedValue({
      total_value_gbp: 0,
      sectors: [],
    });

    const { findByText } = renderWithProviders(<SectorExposureScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('No sector data available')).toBeTruthy();
  });

  it('shows 3 sectors badge in subtitle', async () => {
    mockedGetSectorExposure.mockResolvedValue(mockData);

    const { findByText } = renderWithProviders(<SectorExposureScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(await findByText('3 sectors')).toBeTruthy();
  });
});
