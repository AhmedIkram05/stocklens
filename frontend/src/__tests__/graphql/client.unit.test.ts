/**
 * Tests for `graphql/client.ts` — the typed POST /graphql transport.
 *
 * Covers Bearer injection via ensureValidAccessToken, query/variables body
 * shape, GraphQL-errors → ApiError mapping, non-OK → ApiError(status), and
 * the camelCase → snake_case `toPortfolioPerformance` mapper.
 *
 * HTTP is mocked via jest-fetch-mock; SecureStore via jest.setup.ts.
 */

import { graphqlRequest, PORTFOLIO_DETAIL_QUERY, toPortfolioPerformance } from '@/graphql/client';
import { ApiError } from '@/services/api';
import * as SecureStore from 'expo-secure-store';

const fetchMock = require('jest-fetch-mock');

const ACCESS_TOKEN_KEY = 'stocklens_access_token';
const REFRESH_TOKEN_KEY = 'stocklens_refresh_token';

function setValidToken(expOffset = 3600): void {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expOffset }));
  SecureStore.setItemAsync(ACCESS_TOKEN_KEY, `header.${payload}.sig`);
}

describe('graphqlRequest', () => {
  beforeEach(async () => {
    fetchMock.resetMocks();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  });

  it('POSTs query+variables to /graphql with a Bearer token and returns data', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({ data: { portfolio: { id: '1' } } }), {
      status: 200,
    });

    const result = await graphqlRequest<{ portfolio: { id: string } }>(PORTFOLIO_DETAIL_QUERY, {
      id: '1',
    });

    expect(result).toEqual({ portfolio: { id: '1' } });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/graphql$/);
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe('POST');
    expect(init.headers['Authorization']).toMatch(/^Bearer /);
    expect(JSON.parse(init.body)).toEqual({
      query: PORTFOLIO_DETAIL_QUERY,
      variables: { id: '1' },
    });
  });

  it('omits Authorization when no valid token exists', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ data: {} }), { status: 200 });

    await graphqlRequest('query { __typename }');

    expect(fetchMock.mock.calls[0][1].headers['Authorization']).toBeUndefined();
  });

  it('throws ApiError 400 joining body.errors messages', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(
      JSON.stringify({ errors: [{ message: 'first' }, { message: 'second' }] }),
      { status: 200 },
    );

    const err = await graphqlRequest('query { boom }').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(400);
    expect((err as ApiError).message).toBe('first; second');
  });

  it('throws ApiError(status) with the first GraphQL error on non-OK', async () => {
    setValidToken();
    fetchMock.mockResponseOnce(JSON.stringify({ errors: [{ message: 'Forbidden' }] }), {
      status: 403,
    });

    const err = await graphqlRequest('query { boom }').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).message).toBe('Forbidden');
  });

  it('falls back to a generic message on non-OK non-JSON bodies', async () => {
    setValidToken();
    fetchMock.mockResponseOnce('', { status: 500 });

    const err = await graphqlRequest('query { boom }').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).message).toBe('GraphQL request failed');
  });
});

describe('toPortfolioPerformance', () => {
  it('maps camelCase codegen shape to snake_case, deriving total_cost_basis', () => {
    const result = toPortfolioPerformance({
      __typename: 'PortfolioPerformance',
      portfolioId: 'pid-1',
      portfolioName: 'Retirement',
      totalMarketValue: 2100,
      totalUnrealisedPl: 600,
      totalUnrealisedPlPct: 40,
      dayChange: 50,
      dayChangePct: 2.43,
      twr: 12.5,
      twrAnnualised: 6.1,
      twrStartDate: '2024-01-01',
      twrEndDate: '2025-01-01',
      twrMethodology: 'twr',
      freeCashBalance: 100,
      dataQuality: 'complete',
      totalHoldings: 1,
      calculatedAt: '2025-01-02T00:00:00',
      holdings: [
        {
          __typename: 'HoldingPerformance',
          ticker: 'AAPL',
          shares: 10,
          averageCostBasis: 150,
          currentPrice: 210,
          currency: 'USD',
          marketValue: 2100,
          costBasis: 1500,
          unrealisedPl: 600,
          unrealisedPlPct: 40,
          dayChange: 50,
          dayChangePct: 2.43,
          portfolioWeightPct: 100,
        },
      ],
    });

    expect(result.portfolio_id).toBe('pid-1');
    expect(result.portfolio_name).toBe('Retirement');
    expect(result.total_market_value).toBe(2100);
    expect(result.total_cost_basis).toBe(1500); // 10 × 150 derived
    expect(result.twr_annualised).toBe(6.1);
    expect(result.twr_methodology).toBe('twr');
    expect(result.total_holdings).toBe(1);
    expect(result.holdings[0]).toEqual({
      ticker: 'AAPL',
      shares: 10,
      average_cost_basis: 150,
      current_price: 210,
      market_value: 2100,
      cost_basis: 1500,
      unrealised_pl: 600,
      unrealised_pl_pct: 40,
      day_change: 50,
      day_change_pct: 2.43,
      portfolio_weight_pct: 100,
      currency: 'USD',
    });
  });

  it('nulls optional money fields that arrive as null', () => {
    const result = toPortfolioPerformance({
      __typename: 'PortfolioPerformance',
      portfolioId: 'pid-2',
      portfolioName: 'Empty',
      totalMarketValue: null,
      totalUnrealisedPl: null,
      totalUnrealisedPlPct: null,
      dayChange: null,
      dayChangePct: null,
      twr: null,
      twrAnnualised: null,
      twrStartDate: null,
      twrEndDate: null,
      twrMethodology: 'twr',
      freeCashBalance: 0,
      dataQuality: 'complete',
      totalHoldings: 0,
      calculatedAt: '2025-01-02T00:00:00',
      holdings: [],
    });

    expect(result.total_market_value).toBeNull();
    expect(result.total_cost_basis).toBe(0);
    expect(result.holdings).toEqual([]);
  });
});
