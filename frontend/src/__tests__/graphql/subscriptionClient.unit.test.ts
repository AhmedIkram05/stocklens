/**
 * Tests for `graphql/subscriptionClient.ts`.
 *
 * graphql-ws is fully mocked: asserts the singleton is reused across
 * subscribes, subscribe is called with the doc + ticker variables, `next`
 * reaches the callback, cleanup calls unsubscribe, and the shared client is
 * never disposed per-subscription.
 */

import {
  getSubscriptionClient,
  resetSubscriptionClient,
  subscribeMarketQuote,
  subscribePortfolioValuation,
  MARKET_QUOTE_SUBSCRIPTION,
  PORTFOLIO_VALUATION_SUBSCRIPTION,
} from '@/graphql/subscriptionClient';
import { createClient } from 'graphql-ws';
import * as SecureStore from 'expo-secure-store';

jest.mock('graphql-ws', () => ({ createClient: jest.fn() }));

const mockCreateClient = createClient as jest.Mock;
const ACCESS_TOKEN_KEY = 'stocklens_access_token';

function setValidToken(expOffset = 3600): void {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expOffset }));
  SecureStore.setItemAsync(ACCESS_TOKEN_KEY, `header.${payload}.sig`);
}

describe('subscriptionClient', () => {
  const unsubscribeFn = jest.fn();
  const disposeFn = jest.fn();
  const subscribeFn = jest.fn(() => unsubscribeFn);
  const fakeClient = { subscribe: subscribeFn, dispose: disposeFn };

  beforeEach(async () => {
    mockCreateClient.mockReturnValue(fakeClient);
    subscribeFn.mockClear();
    unsubscribeFn.mockClear();
    disposeFn.mockClear();
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
  });

  it('reuses one shared client across subscribes', async () => {
    const before = mockCreateClient.mock.calls.length;
    const first = getSubscriptionClient();
    const second = getSubscriptionClient();
    expect(second).toBe(first);
    // The singleton may already exist from an earlier test; it must never be
    // recreated within a test run.
    expect(mockCreateClient.mock.calls.length - before).toBeLessThanOrEqual(1);
  });

  it('subscribes with the doc + ticker variables and routes next to the callback', async () => {
    const onNext = jest.fn();
    subscribeMarketQuote('AAPL', onNext);

    expect(subscribeFn).toHaveBeenCalledTimes(1);
    const [payload, sink] = subscribeFn.mock.calls[0] as unknown as [
      unknown,
      { next: (q: unknown) => void },
    ];
    expect(payload).toEqual({ query: MARKET_QUOTE_SUBSCRIPTION, variables: { ticker: 'AAPL' } });

    const quote = { ticker: 'AAPL', price: 210 };
    sink.next({ data: { marketQuote: quote } });
    expect(onNext).toHaveBeenCalledWith(quote);
  });

  it('ignores envelopes without quote data', async () => {
    const onNext = jest.fn();
    subscribeMarketQuote('AAPL', onNext);
    const [, sink] = subscribeFn.mock.calls[0] as unknown as [
      unknown,
      { next: (q: unknown) => void },
    ];

    sink.next({ data: null });
    expect(onNext).not.toHaveBeenCalled();
  });

  it('cleanup calls unsubscribe and never disposes the shared client', async () => {
    const cleanup = subscribeMarketQuote('MSFT', jest.fn());

    cleanup();

    expect(unsubscribeFn).toHaveBeenCalledTimes(1);
    expect(disposeFn).not.toHaveBeenCalled();
  });

  it('supplies a fresh Bearer authToken via connectionParams', async () => {
    setValidToken();
    getSubscriptionClient();
    // First creation call — connectionParams reads the token lazily per (re)connect.
    const opts = mockCreateClient.mock.calls[0][0] as {
      url: string;
      connectionParams: () => Promise<unknown>;
    };
    expect(opts.url).toMatch(/^ws/);
    expect(opts.url).toMatch(/\/graphql$/);
    await expect(opts.connectionParams()).resolves.toEqual({
      authToken: expect.stringMatching(/^Bearer /),
    });
  });

  it('connectionParams returns {} when no token exists', async () => {
    getSubscriptionClient();
    const opts = mockCreateClient.mock.calls[0][0] as {
      connectionParams: () => Promise<unknown>;
    };
    await expect(opts.connectionParams()).resolves.toEqual({});
  });

  it('subscribes portfolio valuation with the portfolio id and routes next', () => {
    const onNext = jest.fn();
    subscribePortfolioValuation('pid-1', onNext);

    expect(subscribeFn).toHaveBeenCalledTimes(1);
    const [payload, sink] = subscribeFn.mock.calls[0] as unknown as [
      unknown,
      { next: (q: unknown) => void },
    ];
    expect(payload).toEqual({
      query: PORTFOLIO_VALUATION_SUBSCRIPTION,
      variables: { portfolioId: 'pid-1' },
    });

    const valuation = { portfolioId: 'pid-1', totalMarketValue: 1200 };
    sink.next({ data: { portfolioValuation: valuation } });
    expect(onNext).toHaveBeenCalledWith(valuation);
  });

  it('ignores valuation envelopes without data', () => {
    const onNext = jest.fn();
    subscribePortfolioValuation('pid-1', onNext);
    const [, sink] = subscribeFn.mock.calls[0] as unknown as [
      unknown,
      { next: (q: unknown) => void },
    ];

    sink.next({ data: null });
    expect(onNext).not.toHaveBeenCalled();
  });

  it('reset disposes the shared socket so the next subscribe reconnects', () => {
    getSubscriptionClient();
    const before = mockCreateClient.mock.calls.length;

    resetSubscriptionClient();
    expect(disposeFn).toHaveBeenCalled();

    getSubscriptionClient();
    expect(mockCreateClient.mock.calls.length).toBe(before + 1);
  });

  it('portfolio valuation cleanup calls unsubscribe', () => {
    const cleanup = subscribePortfolioValuation('pid-1', jest.fn());

    cleanup();

    expect(unsubscribeFn).toHaveBeenCalledTimes(1);
    expect(disposeFn).not.toHaveBeenCalled();
  });
});
