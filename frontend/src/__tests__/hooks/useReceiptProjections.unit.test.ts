/**
 * Unit tests for the pure projection helpers in `useReceiptProjections` —
 * investment-option maths and per-card display derivation.
 */

import {
  buildInvestmentOptions,
  computeStockCardView,
  type Prediction,
  type StockCardViewArgs,
} from '@/hooks/useReceiptProjections';
import { STOCK_PRESETS } from '@/services/stockPresets';
import { periodToYears } from '@/constants/periods';
import { brandColors } from '@/contexts/ThemeContext';
import { formatCurrencyGBP } from '@/utils/formatters';

describe('buildInvestmentOptions', () => {
  it('projects every preset forward over the period', () => {
    const years = periodToYears('5Y');
    const options = buildInvestmentOptions(100, '5Y');

    expect(options).toHaveLength(STOCK_PRESETS.length);
    options.forEach((o) => {
      const expectedFuture = 100 * Math.pow(1 + o.returnRate, years);
      expect(o.futureValue).toBeCloseTo(expectedFuture);
      expect(o.gain).toBeCloseTo(expectedFuture - 100);
      expect(o.percentReturn).toBeCloseTo((expectedFuture / 100 - 1) * 100);
    });
  });
});

describe('computeStockCardView', () => {
  const base: StockCardViewArgs = {
    item: { ticker: 'NVDA', name: 'NVIDIA', returnRate: 0.26 },
    years: '5Y',
    mode: 'future',
    totalAmount: 100,
    historicalRates: {},
    futureRates: {},
    predictions: {},
    mutedColor: '#999999',
  };

  it('future mode without a rate renders the unavailable state', () => {
    const view = computeStockCardView(base);
    expect(view.futureDisplay).toBe('—');
    expect(view.percentDisplay).toBe('N/A');
    expect(view.valueColor).toBe('#999999');
    expect(view.badgeText).toBe('LSTM unavailable');
  });

  it('future mode uses the window rate and the LSTM badge', () => {
    const predictions: Record<string, Prediction> = {
      NVDA: { direction: 'UP', rate: 0.1, confidence: 0.8 },
    };
    const view = computeStockCardView({
      ...base,
      futureRates: { NVDA: 0.1 },
      predictions,
    });
    expect(view.futureDisplay).toBe(formatCurrencyGBP(100 * Math.pow(1.1, periodToYears('5Y'))));
    expect(view.badgeText).toBe('LSTM ↑ · 80%');
    expect(view.badgeColor).toBe(brandColors.green);
  });

  it('past mode uses the historical CAGR and flags the best performer', () => {
    const view = computeStockCardView({
      ...base,
      mode: 'past',
      historicalRates: { NVDA: { '5Y': 0.2 } },
      bestPastTicker: 'NVDA',
    });
    expect(view.percentDisplay).toBe(`${((Math.pow(1.2, 5) - 1) * 100).toFixed(1)}%`);
    expect(view.badgeText).toBe('Overperformer');
    expect(view.badgeColor).toBe(brandColors.green);
  });
});
