/**
 * quoteMerge.ts
 *
 * Pure client-side overlay of a subscription tick onto a `PortfolioPerformance`
 * snapshot (per CONTEXT.md formulas). Derived values are a live overlay,
 * approximate until the next full fetch reconciles; the 60s poll cadence
 * bounds divergence. `calculated_at`/`data_quality` stay server-authored.
 */

import type { PortfolioPerformance } from '../services/portfolios';

export function applyQuoteToPerformance(
  performance: PortfolioPerformance,
  quote: { ticker: string; price?: number | null; previousClose?: number | null },
): PortfolioPerformance {
  if (quote.price == null || quote.price === 0) return performance; // null/0 price -> no-op
  const holdings = performance.holdings.map((h) => {
    if (h.ticker !== quote.ticker) return h;
    const market_value = h.shares * quote.price!;
    const cost_basis = h.shares * h.average_cost_basis;
    const unrealised_pl = market_value - cost_basis;
    const unrealised_pl_pct = cost_basis ? (unrealised_pl / cost_basis) * 100 : null;
    // HoldingPerformance has no previous_close — prefer quote.previousClose,
    // fallback to implied prev from last day_change, else current_price (pct -> null-safe).
    const prevClose =
      quote.previousClose ??
      (h.day_change != null && h.current_price != null
        ? h.current_price - h.day_change / Math.max(h.shares, 1)
        : (h.current_price ?? quote.price!));
    const day_change = h.shares * (quote.price! - prevClose);
    const day_change_pct = prevClose ? ((quote.price! - prevClose) / prevClose) * 100 : null;
    return {
      ...h,
      current_price: quote.price!,
      market_value,
      unrealised_pl,
      unrealised_pl_pct,
      day_change,
      day_change_pct,
    };
  });
  // Portfolio-level: recompute ALL sums + weights (cheap, N small).
  const total_market_value = holdings.reduce((s, h) => s + (h.market_value ?? 0), 0);
  const total_unrealised_pl = holdings.reduce((s, h) => s + (h.unrealised_pl ?? 0), 0);
  const total_cost_basis = holdings.reduce((s, h) => s + h.shares * h.average_cost_basis, 0);
  const total_unrealised_pl_pct = total_cost_basis
    ? (total_unrealised_pl / total_cost_basis) * 100
    : null;
  const day_change = holdings.reduce((s, h) => s + (h.day_change ?? 0), 0);
  // Day % = day_change / prev-day portfolio value (not cost basis).
  const prev_day_value = total_market_value - day_change;
  const day_change_pct = prev_day_value ? (day_change / prev_day_value) * 100 : null;
  const weighted = holdings.map((h) => ({
    ...h,
    portfolio_weight_pct: total_market_value
      ? ((h.market_value ?? 0) / total_market_value) * 100
      : null,
  }));
  return {
    ...performance,
    total_market_value,
    total_unrealised_pl,
    total_unrealised_pl_pct,
    day_change,
    day_change_pct,
    holdings: weighted,
  };
}
