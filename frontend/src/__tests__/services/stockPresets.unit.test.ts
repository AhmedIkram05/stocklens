import { STOCK_PRESETS, PRESET_RATES } from '@/services/stockPresets';
import { PREFETCH_TICKERS } from '@/services/dataService';

jest.mock('@/services/dataService', () => ({
  PREFETCH_TICKERS: ['NVDA', 'AAPL', 'MSFT', 'TSLA', 'NKE', 'AMZN', 'GOOGL', 'META', 'JPM', 'UNH'],
}));

describe('stockPresets', () => {
  it('exports PRESET_RATES with correct values', () => {
    expect(PRESET_RATES).toEqual({
      NVDA: 0.26,
      AAPL: 0.11,
      MSFT: 0.18,
      TSLA: 0.25,
      NKE: 0.08,
      AMZN: 0.17,
      GOOGL: 0.16,
      META: 0.2,
      JPM: 0.1,
      UNH: 0.12,
    });
  });

  it('exports correct company names via STOCK_PRESETS', () => {
    expect(STOCK_PRESETS.find((p) => p.ticker === 'NVDA')?.name).toBe('NVIDIA');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'AAPL')?.name).toBe('Apple');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'MSFT')?.name).toBe('Microsoft');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'TSLA')?.name).toBe('Tesla');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'NKE')?.name).toBe('Nike');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'AMZN')?.name).toBe('Amazon');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'GOOGL')?.name).toBe('Alphabet');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'META')?.name).toBe('Meta');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'JPM')?.name).toBe('JPMorgan Chase');
    expect(STOCK_PRESETS.find((p) => p.ticker === 'UNH')?.name).toBe('UnitedHealth');
  });

  it('builds STOCK_PRESETS from PREFETCH_TICKERS with correct structure', () => {
    expect(STOCK_PRESETS).toHaveLength(10);

    STOCK_PRESETS.forEach((preset) => {
      expect(preset).toHaveProperty('name');
      expect(preset).toHaveProperty('ticker');
      expect(preset).toHaveProperty('returnRate');
      expect(typeof preset.name).toBe('string');
      expect(typeof preset.ticker).toBe('string');
      expect(typeof preset.returnRate).toBe('number');
    });

    const nvda = STOCK_PRESETS.find((p) => p.ticker === 'NVDA');
    expect(nvda).toEqual({ name: 'NVIDIA', ticker: 'NVDA', returnRate: 0.26 });

    const aapl = STOCK_PRESETS.find((p) => p.ticker === 'AAPL');
    expect(aapl).toEqual({ name: 'Apple', ticker: 'AAPL', returnRate: 0.11 });

    const msft = STOCK_PRESETS.find((p) => p.ticker === 'MSFT');
    expect(msft).toEqual({ name: 'Microsoft', ticker: 'MSFT', returnRate: 0.18 });
  });

  it('has returnRate defined for all PREFETCH_TICKERS', () => {
    STOCK_PRESETS.forEach((preset) => {
      expect(preset.returnRate).toBeGreaterThanOrEqual(0);
      expect(preset.returnRate).toBeLessThan(1);
    });
  });

  it('matches PREFETCH_TICKERS order in STOCK_PRESETS', () => {
    STOCK_PRESETS.forEach((preset, index) => {
      expect(preset.ticker).toBe(PREFETCH_TICKERS[index]);
    });
  });
});
