/**
 * Tests for `projectionService` financial calculations.
 * Covers CAGR computation, projecting using historical series, and
 * fallbacks to preset rates when history is insufficient.
 */

jest.mock('@/services/market', () => ({
  marketService: {
    getOHLCV: jest.fn(),
  },
}));

import { marketService } from '@/services/market';
import * as projectionService from '@/services/projectionService';
import { PRESET_RATES } from '@/services/stockPresets';
import { buildOHLCVSeries } from '../fixtures';

const mockedMarketService = marketService as jest.Mocked<typeof marketService>;

describe('projectionService.computeCAGRFromSeries', () => {
  it('calculates CAGR using first and last entries in the series', () => {
    const series = [
      { date: '2020-01-01', close: 100, adjusted_close: 100 },
      { date: '2021-01-01', close: 121, adjusted_close: 121 },
    ];

    const cagr = projectionService.computeCAGRFromSeries(series as any);

    expect(cagr).not.toBeNull();
    expect(cagr!).toBeCloseTo(0.21, 2); // (121/100)^(1/1) - 1 = 0.21
  });

  it('returns null when the series is shorter than two points or invalid', () => {
    expect(projectionService.computeCAGRFromSeries([])).toBeNull();
    expect(
      projectionService.computeCAGRFromSeries([{ date: '2020-01-01', close: 0 } as any]),
    ).toBeNull();
  });
});

describe('projectionService.projectUsingHistoricalCAGR', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('uses fetched CAGR when stock history is available', async () => {
    // Use fixture to generate 60 months of data with 12% growth (1% per month)
    const historicalSeries = buildOHLCVSeries(60, 0.01, 100);

    mockedMarketService.getOHLCV.mockResolvedValue(historicalSeries);

    const result = await projectionService.projectUsingHistoricalCAGR(1000, 'NVDA', 5);

    // The fixture uses 1% monthly growth which compounds to ~12.7% annual CAGR
    expect(result.rate).toBeCloseTo(0.127, 2);
    expect(result.futureValue).toBeCloseTo(1000 * Math.pow(1 + result.rate, 5), 5);
  });

  it('falls back to preset rates when historical data is insufficient', async () => {
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2024-01-01', adjusted_close: 150, close: 150 },
    ] as any);

    const result = await projectionService.projectUsingHistoricalCAGR(500, 'aapl', 3);

    const presetRate = PRESET_RATES.AAPL;
    expect(result.rate).toBe(presetRate);
    expect(result.futureValue).toBeCloseTo(500 * Math.pow(1 + presetRate, 3), 5);
  });
});
