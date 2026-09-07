/**
 * Tests for `graphql/quoteMerge.ts` — pure tick-overlay recompute.
 *
 * Hand-computed expectations (CONTEXT.md formulas):
 * Market Value = shares × price; Unrealised = mv − cost_basis;
 * Day Change = shares × (price − prev_close); Day % vs prev-day value;
 * Weight = mv / total × 100.
 */

import { applyQuoteToPerformance } from '@/graphql/quoteMerge';
import type { PortfolioPerformance, HoldingPerformance } from '@/services/portfolios';

function holding(overrides: Partial<HoldingPerformance> = {}): HoldingPerformance {
  return {
    ticker: 'AAPL',
    shares: 10,
    average_cost_basis: 150,
    current_price: 200,
    market_value: 2000,
    cost_basis: 1500,
    unrealised_pl: 500,
    unrealised_pl_pct: (500 / 1500) * 100,
    day_change: 50,
    day_change_pct: (50 / 1950) * 100,
    portfolio_weight_pct: 100,
    currency: 'USD',
    ...overrides,
  };
}

function perf(holdings: HoldingPerformance[]): PortfolioPerformance {
  return {
    portfolio_id: 'pid-1',
    portfolio_name: 'Test',
    total_market_value: 2000,
    total_cost_basis: 1500,
    total_unrealised_pl: 500,
    total_unrealised_pl_pct: (500 / 1500) * 100,
    day_change: 50,
    day_change_pct: (50 / 1950) * 100,
    free_cash_balance: 100,
    twr: 12.5,
    twr_annualised: 6.1,
    twr_start_date: '2024-01-01',
    twr_end_date: '2025-01-01',
    twr_methodology: 'twr',
    data_quality: 'complete',
    holdings,
    total_holdings: holdings.length,
    calculated_at: '2025-01-02T00:00:00',
  };
}

describe('applyQuoteToPerformance', () => {
  it('recomputes holding + portfolio values on a price-up tick', () => {
    const out = applyQuoteToPerformance(perf([holding()]), {
      ticker: 'AAPL',
      price: 210,
      previousClose: 205,
    });

    const h = out.holdings[0];
    expect(h.current_price).toBe(210);
    expect(h.market_value).toBe(2100); // 10 × 210
    expect(h.unrealised_pl).toBe(600); // 2100 − 1500
    expect(h.unrealised_pl_pct).toBeCloseTo(40, 10); // 600/1500 × 100
    expect(h.day_change).toBe(50); // 10 × (210 − 205)
    expect(h.day_change_pct).toBeCloseTo((5 / 205) * 100, 10);
    expect(h.portfolio_weight_pct).toBe(100);

    expect(out.total_market_value).toBe(2100);
    expect(out.total_unrealised_pl).toBe(600);
    expect(out.total_unrealised_pl_pct).toBeCloseTo(40, 10);
    expect(out.day_change).toBe(50);
    expect(out.day_change_pct).toBeCloseTo((50 / 2050) * 100, 10);
    // Server-authored fields untouched
    expect(out.calculated_at).toBe('2025-01-02T00:00:00');
    expect(out.data_quality).toBe('complete');
    expect(out.free_cash_balance).toBe(100);
  });

  it('ignores ticks for unknown tickers (values equal, no crash)', () => {
    const before = perf([holding()]);
    const out = applyQuoteToPerformance(before, {
      ticker: 'MSFT',
      price: 500,
      previousClose: 490,
    });

    expect(out).toEqual(before);
  });

  it('is a no-op (same ref) on null or zero prices', () => {
    const before = perf([holding()]);

    expect(applyQuoteToPerformance(before, { ticker: 'AAPL', price: null })).toBe(before);
    expect(applyQuoteToPerformance(before, { ticker: 'AAPL', price: 0 })).toBe(before);
  });

  it('recomputes sums + weights across holdings, leaving others intact', () => {
    const msft = holding({
      ticker: 'MSFT',
      shares: 5,
      average_cost_basis: 300,
      current_price: 400,
      market_value: 2000,
      cost_basis: 1500,
      unrealised_pl: 500,
      unrealised_pl_pct: (500 / 1500) * 100,
      day_change: 0,
      day_change_pct: 0,
      portfolio_weight_pct: 50,
      currency: 'USD',
    });
    const out = applyQuoteToPerformance(perf([holding(), msft]), {
      ticker: 'AAPL',
      price: 210,
      previousClose: 205,
    });

    // MSFT untouched except its weight
    expect(out.holdings[1].current_price).toBe(400);
    expect(out.holdings[1].market_value).toBe(2000);
    // Totals: mv 2100 + 2000; cost 1500 + 1500; pl 600 + 500
    expect(out.total_market_value).toBe(4100);
    expect(out.total_unrealised_pl).toBe(1100);
    expect(out.total_unrealised_pl_pct).toBeCloseTo((1100 / 3000) * 100, 10);
    expect(out.day_change).toBe(50); // 50 + 0
    expect(out.holdings[0].portfolio_weight_pct).toBeCloseTo((2100 / 4100) * 100, 10);
    expect(out.holdings[1].portfolio_weight_pct).toBeCloseTo((2000 / 4100) * 100, 10);
  });

  it('falls back to implied prev close when the tick lacks previousClose', () => {
    // Implied prev = 200 − 50/10 = 195; quote 210 → day = 10 × 15 = 150.
    const out = applyQuoteToPerformance(perf([holding()]), { ticker: 'AAPL', price: 210 });

    expect(out.holdings[0].day_change).toBe(150);
    expect(out.holdings[0].day_change_pct).toBeCloseTo((15 / 195) * 100, 10);
  });
});
