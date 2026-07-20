/**
 * Tests for `projectionService` — CAGR, future value projections, and LSTM.
 * Covers CAGR computation, projection using historical series,
 * fallbacks to preset rates, and combined projection with LSTM.
 */

jest.mock('@/services/market', () => ({
  marketService: {
    getOHLCV: jest.fn(),
  },
}));

import { marketService } from '@/services/market';
import * as projectionService from '@/services/projectionService';
import { PRESET_RATES } from '@/services/stockPresets';

const mockedMarketService = marketService as jest.Mocked<typeof marketService>;

describe('projectionService.computeCAGRFromSeries', () => {
  it('calculates CAGR using first and last entries in the series', () => {
    const series = [
      { date: '2020-01-01', close: 100, adjusted_close: 100 },
      { date: '2021-01-01', close: 121, adjusted_close: 121 },
    ] as any;

    const cagr = projectionService.computeCAGRFromSeries(series);

    expect(cagr).not.toBeNull();
    expect(cagr!).toBeCloseTo(0.21, 2);
  });

  it('returns null when the series is shorter than two points', () => {
    expect(projectionService.computeCAGRFromSeries([])).toBeNull();
    expect(
      projectionService.computeCAGRFromSeries([{ date: '2020-01-01', close: 0 } as any]),
    ).toBeNull();
  });

  it('returns null when first or last price is missing or zero', () => {
    const series = [
      { date: '2020-01-01', adjusted_close: 0 },
      { date: '2021-01-01', adjusted_close: 100 },
    ] as any;
    expect(projectionService.computeCAGRFromSeries(series)).toBeNull();
  });
});

describe('projectionService.getCAGR', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns CAGR from backend OHLCV data', async () => {
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2020-01-01', adjusted_close: 100 },
      { date: '2021-01-01', adjusted_close: 121 },
    ] as any);

    const cagr = await projectionService.getCAGR('AAPL');

    expect(cagr).toBeCloseTo(0.21, 2);
  });

  it('returns null when OHLCV data has fewer than 2 points', async () => {
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2024-01-01', adjusted_close: 150 },
    ] as any);
    expect(await projectionService.getCAGR('AAPL')).toBeNull();
  });

  it('returns null when API call fails', async () => {
    mockedMarketService.getOHLCV.mockRejectedValue(new Error('API error'));
    expect(await projectionService.getCAGR('AAPL')).toBeNull();
  });
});

describe('projectionService.projectUsingHistoricalCAGR', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('uses fetched CAGR when stock history is available', async () => {
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2020-01-01', adjusted_close: 100 },
      { date: '2021-01-01', adjusted_close: 113 },
    ] as any);

    const result = await projectionService.projectUsingHistoricalCAGR(1000, 'NVDA', 5);

    expect(result.rate).toBeGreaterThan(0);
    expect(result.futureValue).toBeGreaterThan(1000);
  });

  it('falls back to preset rates when historical data fails', async () => {
    mockedMarketService.getOHLCV.mockRejectedValue(new Error('fail'));

    const result = await projectionService.projectUsingHistoricalCAGR(500, 'aapl', 3);

    const presetRate = PRESET_RATES.AAPL;
    expect(result.rate).toBe(presetRate);
    expect(result.futureValue).toBeCloseTo(500 * Math.pow(1 + presetRate, 3), 5);
  });

  it('uses 0.1 default fallback when no history and no preset', async () => {
    mockedMarketService.getOHLCV.mockRejectedValue(new Error('fail'));

    const result = await projectionService.projectUsingHistoricalCAGR(1000, 'UNKNOWN', 2);

    expect(result.rate).toBe(0.1);
  });
});

jest.mock('@/services/prediction', () => ({
  predictionService: {
    getPrediction: jest.fn(),
  },
}));

import { predictionService as mockedPredictionService } from '@/services/prediction';

describe('projectionService.getHistoricalCAGRForPeriod', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('computes CAGR over the selected lookback window', async () => {
    const series = [
      { date: '2019-01-01', adjusted_close: 100 },
      { date: '2024-01-01', adjusted_close: 200 },
    ] as any;
    mockedMarketService.getOHLCV.mockResolvedValue(series);

    const cagr = await projectionService.getHistoricalCAGRForPeriod('NVDA', '5Y');

    expect(cagr).not.toBeNull();
    expect(cagr!).toBeCloseTo(Math.pow(2, 1 / 5) - 1, 4);
  });

  it('returns null when fewer than two points are available', async () => {
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2024-01-01', adjusted_close: 150 },
    ] as any);
    expect(await projectionService.getHistoricalCAGRForPeriod('NVDA', '5Y')).toBeNull();
  });
});

describe('projectionService.getHistoricalCAGRFromToday', () => {
  it('delegates to getCAGR', async () => {
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2020-01-01', adjusted_close: 100 },
      { date: '2021-01-01', adjusted_close: 121 },
    ] as any);

    const cagr = await projectionService.getHistoricalCAGRFromToday('AAPL');
    expect(cagr).not.toBeNull();
  });
});

describe('projectionService.getLSTMPrediction', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns prediction when available', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockResolvedValue({
      direction: 'UP',
      confidence: 0.85,
      model_version: 'champion',
    });

    const result = await projectionService.getLSTMPrediction('AAPL');

    expect(result).not.toBeNull();
    expect(result!.direction).toBe('UP');
    expect(result!.confidence).toBe(0.85);
  });

  it('returns null when prediction fails', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockRejectedValue(new Error('fail'));
    expect(await projectionService.getLSTMPrediction('AAPL')).toBeNull();
  });
});

describe('projectionService.getCombinedProjection', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns combined LSTM + CAGR projection', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockResolvedValue({
      direction: 'UP',
      confidence: 0.8,
      model_version: 'champion',
    });
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2019-01-01', adjusted_close: 100 },
      { date: '2024-01-01', adjusted_close: 200 },
    ] as any);

    const proj = await projectionService.getCombinedProjection('NVDA', '5Y');

    expect(proj).not.toBeNull();
    expect(proj!.direction).toBe('UP');
    expect(proj!.rate).toBeCloseTo(Math.pow(2, 1 / 5) - 1, 4);
    expect(proj!.confidence).toBe(0.8);
    expect(proj!.model_version).toBe('champion');
  });

  it('falls back to CAGR-only when LSTM fails', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockRejectedValue(new Error('fail'));
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2019-01-01', adjusted_close: 100 },
      { date: '2024-01-01', adjusted_close: 200 },
    ] as any);

    const proj = await projectionService.getCombinedProjection('NVDA', '5Y');

    expect(proj).not.toBeNull();
    expect(proj!.direction).toBe('UP');
    expect(proj!.confidence).toBe(0.5);
    expect(proj!.model_version).toBe('cagr-fallback');
  });

  it('sets direction to DOWN when CAGR is negative', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockRejectedValue(new Error('fail'));
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2019-01-01', adjusted_close: 200 },
      { date: '2024-01-01', adjusted_close: 100 },
    ] as any);

    const proj = await projectionService.getCombinedProjection('NVDA', '5Y');

    expect(proj).not.toBeNull();
    expect(proj!.direction).toBe('DOWN');
    expect(proj!.confidence).toBe(0.5);
  });

  it('sets direction to FLAT when CAGR is zero', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockRejectedValue(new Error('fail'));
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2019-01-01', adjusted_close: 100 },
      { date: '2024-01-01', adjusted_close: 100 },
    ] as any);

    const proj = await projectionService.getCombinedProjection('NVDA', '5Y');

    expect(proj).not.toBeNull();
    expect(proj!.direction).toBe('FLAT');
  });

  it('returns null when CAGR is null and LSTM fails', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockRejectedValue(new Error('fail'));
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2024-01-01', adjusted_close: 100 },
    ] as any);

    const proj = await projectionService.getCombinedProjection('NVDA', '5Y');

    expect(proj).toBeNull();
  });

  it('uses full-history CAGR when periodLabel not provided', async () => {
    (mockedPredictionService.getPrediction as jest.Mock).mockResolvedValue({
      direction: 'UP',
      confidence: 0.75,
      model_version: 'v2',
    });
    mockedMarketService.getOHLCV.mockResolvedValue([
      { date: '2018-01-01', adjusted_close: 50 },
      { date: '2024-01-01', adjusted_close: 100 },
    ] as any);

    const proj = await projectionService.getCombinedProjection('NVDA');

    expect(proj).not.toBeNull();
    expect(proj!.direction).toBe('UP');
    expect(mockedMarketService.getOHLCV).toHaveBeenCalledWith('NVDA');
  });
});
