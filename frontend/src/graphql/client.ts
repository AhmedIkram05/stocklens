/**
 * client.ts
 *
 * Minimal typed transport for the read-only GraphQL facade (`POST /graphql`).
 * Reuses the JWT refresh + SecureStore plumbing in `services/api.ts` via
 * `apiService.ensureValidAccessToken()` (token pre-freshened, no retry needed).
 */

import { API_BASE_URL, ApiError, apiService } from '../services/api';
import type { PortfolioDetailQuery } from './generated';
import type { PortfolioPerformance } from '../services/portfolios';

export async function graphqlRequest<TData, TVars = Record<string, unknown>>(
  query: string,
  variables?: TVars,
): Promise<TData> {
  const token = await apiService.ensureValidAccessToken();
  const res = await fetch(`${API_BASE_URL}/graphql`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ query, variables }),
  });
  const body = (await res.json().catch(() => ({}))) as {
    data?: unknown;
    errors?: { message?: string }[];
    detail?: string;
  };
  if (!res.ok)
    throw new ApiError(
      res.status,
      body?.errors?.[0]?.message ?? body?.detail ?? 'GraphQL request failed',
    );
  if (body.errors?.length) throw new ApiError(400, body.errors.map((e) => e.message).join('; '));
  return body.data as TData;
}

/** Runtime document string for codegen's `PortfolioDetail` operation (kept in sync by eye). */
export const PORTFOLIO_DETAIL_QUERY = `
query PortfolioDetail($id: ID!) {
  portfolio(id: $id) {
    id
    name
    performance {
      portfolioId
      portfolioName
      totalMarketValue
      totalUnrealisedPl
      totalUnrealisedPlPct
      dayChange
      dayChangePct
      twr
      twrAnnualised
      twrStartDate
      twrEndDate
      twrMethodology
      freeCashBalance
      dataQuality
      totalHoldings
      calculatedAt
      holdings {
        ticker
        shares
        averageCostBasis
        currentPrice
        currency
        marketValue
        costBasis
        unrealisedPl
        unrealisedPlPct
        dayChange
        dayChangePct
        portfolioWeightPct
      }
    }
  }
}
`;

type DetailPortfolio = NonNullable<PortfolioDetailQuery['portfolio']>;

/**
 * Map the camelCase codegen shape back to the snake_case `PortfolioPerformance`
 * the screen renders, so the render JSX stays untouched. `total_cost_basis`
 * is re-derived from holdings (same formula as the backend).
 */
export function toPortfolioPerformance(p: DetailPortfolio['performance']): PortfolioPerformance {
  return {
    portfolio_id: p.portfolioId,
    portfolio_name: p.portfolioName,
    total_market_value: p.totalMarketValue ?? null,
    total_cost_basis: p.holdings.reduce((s, h) => s + h.shares * h.averageCostBasis, 0),
    total_unrealised_pl: p.totalUnrealisedPl ?? null,
    total_unrealised_pl_pct: p.totalUnrealisedPlPct ?? null,
    day_change: p.dayChange ?? null,
    day_change_pct: p.dayChangePct ?? null,
    free_cash_balance: p.freeCashBalance,
    twr: p.twr ?? null,
    twr_annualised: p.twrAnnualised ?? null,
    twr_start_date: p.twrStartDate ?? null,
    twr_end_date: p.twrEndDate ?? null,
    twr_methodology: p.twrMethodology,
    data_quality: p.dataQuality,
    holdings: p.holdings.map((h) => ({
      ticker: h.ticker,
      shares: h.shares,
      average_cost_basis: h.averageCostBasis,
      current_price: h.currentPrice ?? null,
      market_value: h.marketValue ?? null,
      cost_basis: h.costBasis,
      unrealised_pl: h.unrealisedPl ?? null,
      unrealised_pl_pct: h.unrealisedPlPct ?? null,
      day_change: h.dayChange ?? null,
      day_change_pct: h.dayChangePct ?? null,
      portfolio_weight_pct: h.portfolioWeightPct ?? null,
      currency: h.currency,
    })),
    total_holdings: p.totalHoldings,
    calculated_at: p.calculatedAt,
  };
}

export type { DetailPortfolio };
