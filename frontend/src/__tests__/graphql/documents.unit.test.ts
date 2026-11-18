/**
 * Guards the hand-copied runtime documents against drift from the `.graphql`
 * files that produce the generated operation types.
 *
 * Codegen types come from the `.graphql` files; the app sends the strings in
 * `client.ts` / `subscriptionClient.ts`. If they diverge, the types describe a
 * query the client does not actually send, and CI would stay green.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { parse, print } from 'graphql';

import { PORTFOLIO_DETAIL_QUERY } from '@/graphql/client';
import {
  MARKET_QUOTE_SUBSCRIPTION,
  PORTFOLIO_VALUATION_SUBSCRIPTION,
} from '@/graphql/subscriptionClient';

const DOCS_DIR = join(__dirname, '../../graphql');

const canonical = (source: string) => print(parse(source));
const readDoc = (name: string) => readFileSync(join(DOCS_DIR, name), 'utf8');

describe('runtime documents match their .graphql sources', () => {
  it('PortfolioDetail', () => {
    expect(canonical(PORTFOLIO_DETAIL_QUERY)).toBe(canonical(readDoc('portfolioDetail.graphql')));
  });

  it('MarketQuote', () => {
    expect(canonical(MARKET_QUOTE_SUBSCRIPTION)).toBe(
      canonical(readDoc('marketQuote.subscription.graphql')),
    );
  });

  it('PortfolioValuation', () => {
    expect(canonical(PORTFOLIO_VALUATION_SUBSCRIPTION)).toBe(
      canonical(readDoc('portfolioValuation.subscription.graphql')),
    );
  });
});
