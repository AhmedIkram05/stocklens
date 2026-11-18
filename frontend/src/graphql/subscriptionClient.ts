/**
 * subscriptionClient.ts
 *
 * Singleton graphql-ws client for the `marketQuote` subscription feed.
 * graphql-ws multiplexes N tickers over ONE shared socket + reconnects
 * natively; a fresh token is supplied via `connectionParams` on every
 * (re)connect. Singleton avoids the per-call `createClient` socket leak.
 */

import { createClient, type Client } from 'graphql-ws';
import { API_BASE_URL, apiService } from '../services/api';
import type { MarketQuoteSubscription, PortfolioValuationSubscription } from './generated';

export type MarketQuotePayload = MarketQuoteSubscription['marketQuote'];
export type PortfolioValuationPayload = PortfolioValuationSubscription['portfolioValuation'];

/** Runtime document string for codegen's `MarketQuote` operation (kept in sync by eye). */
export const MARKET_QUOTE_SUBSCRIPTION = `
subscription MarketQuote($ticker: String!) {
  marketQuote(ticker: $ticker) {
    ticker
    price
    change
    changePct
    previousClose
    timestamp
  }
}
`;

const wsUrl = (base: string) => base.replace(/^http/, 'ws') + '/graphql';

let sharedClient: Client | null = null;

export function getSubscriptionClient(): Client {
  if (!sharedClient) {
    sharedClient = createClient({
      url: wsUrl(API_BASE_URL),
      connectionParams: async () => {
        const token = await apiService.ensureValidAccessToken();
        return token ? { authToken: `Bearer ${token}` } : {};
      },
      retryAttempts: 5,
    });
  }
  return sharedClient;
}

export function subscribeMarketQuote(
  ticker: string,
  onNext: (quote: MarketQuotePayload) => void,
  onError?: (err: unknown) => void,
): () => void {
  const client = getSubscriptionClient();
  const unsubscribe = client.subscribe(
    { query: MARKET_QUOTE_SUBSCRIPTION, variables: { ticker } },
    {
      // graphql-ws delivers the execution-result envelope — unwrap to the payload.
      next: (result) => {
        const quote = (result as { data?: { marketQuote?: MarketQuotePayload } })?.data
          ?.marketQuote;
        if (quote) onNext(quote);
      },
      error: onError ?? (() => {}),
      complete: () => {},
    },
  );
  // NOTE: do NOT dispose the shared client per subscription — graphql-ws multiplexes
  // N subscriptions over ONE socket. Dispose only on app teardown / logout.
  return () => {
    unsubscribe();
  };
}

/** Runtime document string for codegen's `PortfolioValuation` operation (kept in sync by eye). */
export const PORTFOLIO_VALUATION_SUBSCRIPTION = `
subscription PortfolioValuation($portfolioId: ID!) {
  portfolioValuation(portfolioId: $portfolioId) {
    portfolioId
    portfolioName
    totalMarketValue
    totalCostBasis
    totalUnrealisedPl
    totalUnrealisedPlPct
    dayChange
    dayChangePct
    freeCashBalance
    totalHoldings
    dataQuality
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
`;

/**
 * One server-computed valuation stream per portfolio. Replaces the per-ticker
 * fan-out plus client-side merging: the holdings' derived values arrive already
 * FX-converted and summed, so the screen just overlays the payload.
 */
export function subscribePortfolioValuation(
  portfolioId: string,
  onNext: (valuation: PortfolioValuationPayload) => void,
  onError?: (err: unknown) => void,
): () => void {
  const client = getSubscriptionClient();
  const unsubscribe = client.subscribe(
    { query: PORTFOLIO_VALUATION_SUBSCRIPTION, variables: { portfolioId } },
    {
      next: (result) => {
        const valuation = (result as { data?: { portfolioValuation?: PortfolioValuationPayload } })
          ?.data?.portfolioValuation;
        if (valuation) onNext(valuation);
      },
      error: onError ?? (() => {}),
      complete: () => {},
    },
  );
  return () => {
    unsubscribe();
  };
}
