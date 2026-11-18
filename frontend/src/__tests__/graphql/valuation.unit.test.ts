/**
 * Tests for `graphql/client.ts::applyValuation`.
 *
 * A server valuation replaces the price-derived fields wholesale (totals,
 * holdings, weights) while preserving TWR fields from the last full fetch.
 */

import { applyValuation } from '@/graphql/client';
import type { PortfolioValuationPayload } from '@/graphql/subscriptionClient';
import type { PortfolioPerformance } from '@/services/portfolios';

const performance: PortfolioPerformance = {
  portfolio_id: 'pid-1',
  portfolio_name: 'Retirement',
  total_market_value: 1000,
  total_cost_basis: 800,
  total_unrealised_pl: 200,
  total_unrealised_pl_pct: 25,
  day_change: 10,
  day_change_pct: 1,
  free_cash_balance: 5,
  twr: 12.5,
  twr_annualised: 6.1,
  twr_start_date: '2024-01-01',
  twr_end_date: '2025-01-01',
  twr_methodology: 'cash-flow-based',
  data_quality: 'complete',
  holdings: [
    {
      ticker: 'AAPL',
      shares: 10,
      average_cost_basis: 80,
      current_price: 100,
      market_value: 1000,
      cost_basis: 800,
      unrealised_pl: 200,
      unrealised_pl_pct: 25,
      day_change: 10,
      day_change_pct: 1,
      portfolio_weight_pct: 100,
      currency: 'GBP',
    },
  ],
  total_holdings: 1,
  calculated_at: '2025-01-02T00:00:00',
};

const valuation: PortfolioValuationPayload = {
  portfolioId: 'pid-1',
  portfolioName: 'Retirement',
  totalMarketValue: 1200,
  totalCostBasis: 800,
  totalUnrealisedPl: 400,
  totalUnrealisedPlPct: 50,
  dayChange: 20,
  dayChangePct: 1.7,
  freeCashBalance: 5,
  totalHoldings: 1,
  dataQuality: 'complete',
  calculatedAt: '2025-01-02T00:01:00',
  holdings: [
    {
      ticker: 'AAPL',
      shares: 10,
      averageCostBasis: 80,
      currentPrice: 120,
      currency: 'GBP',
      marketValue: 1200,
      costBasis: 800,
      unrealisedPl: 400,
      unrealisedPlPct: 50,
      dayChange: 20,
      dayChangePct: 1.7,
      portfolioWeightPct: 100,
    },
  ],
};

describe('applyValuation', () => {
  it('replaces price-derived totals and holdings', () => {
    const result = applyValuation(performance, valuation);

    expect(result.total_market_value).toBe(1200);
    expect(result.total_unrealised_pl).toBe(400);
    expect(result.total_unrealised_pl_pct).toBe(50);
    expect(result.day_change).toBe(20);
    expect(result.calculated_at).toBe('2025-01-02T00:01:00');
    expect(result.holdings[0]).toMatchObject({
      ticker: 'AAPL',
      current_price: 120,
      market_value: 1200,
      unrealised_pl: 400,
      currency: 'GBP',
    });
  });

  it('preserves TWR and identity from the last full fetch', () => {
    const result = applyValuation(performance, valuation);

    expect(result.portfolio_id).toBe('pid-1');
    expect(result.portfolio_name).toBe('Retirement');
    expect(result.twr).toBe(12.5);
    expect(result.twr_annualised).toBe(6.1);
    expect(result.twr_methodology).toBe('cash-flow-based');
  });

  it('keeps the last known totals when the server cannot price the portfolio', () => {
    const result = applyValuation(performance, {
      ...valuation,
      totalMarketValue: null,
      totalUnrealisedPl: null,
      totalUnrealisedPlPct: null,
      dayChange: null,
      dayChangePct: null,
      dataQuality: 'partial',
    });

    expect(result.total_market_value).toBe(1000);
    expect(result.total_unrealised_pl).toBe(200);
    expect(result.day_change).toBe(10);
    expect(result.data_quality).toBe('partial');
  });
});
