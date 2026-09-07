export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = {
  [_ in K]?: never;
};
export type Incremental<T> =
  T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string };
  String: { input: string; output: string };
  Boolean: { input: boolean; output: boolean };
  Int: { input: number; output: number };
  Float: { input: number; output: number };
  /** Date (isoformat) */
  Date: { input: string; output: string };
  /** Date with time (isoformat) */
  DateTime: { input: string; output: string };
};

export type BenchmarkComparison = {
  __typename?: 'BenchmarkComparison';
  benchmarkCumulativeReturns: Array<CumulativeReturn>;
  benchmarkReturn?: Maybe<Scalars['Float']['output']>;
  benchmarkTicker: Scalars['String']['output'];
  calculatedAt: Scalars['DateTime']['output'];
  dailyReturnsCount: Scalars['Int']['output'];
  excessReturnAlpha?: Maybe<Scalars['Float']['output']>;
  informationRatio?: Maybe<Scalars['Float']['output']>;
  methodology: Scalars['String']['output'];
  periodEnd: Scalars['Date']['output'];
  periodStart: Scalars['Date']['output'];
  portfolioCumulativeReturns: Array<CumulativeReturn>;
  portfolioId: Scalars['ID']['output'];
  portfolioReturn?: Maybe<Scalars['Float']['output']>;
  trackingError?: Maybe<Scalars['Float']['output']>;
};

export type CashFlow = {
  __typename?: 'CashFlow';
  amount: Scalars['Float']['output'];
  createdAt: Scalars['DateTime']['output'];
  id: Scalars['ID']['output'];
  notes?: Maybe<Scalars['String']['output']>;
  portfolioId: Scalars['ID']['output'];
  source: Scalars['String']['output'];
  sourceId?: Maybe<Scalars['String']['output']>;
};

export type CumulativeReturn = {
  __typename?: 'CumulativeReturn';
  date: Scalars['Date']['output'];
  value: Scalars['Float']['output'];
};

export type Holding = {
  __typename?: 'Holding';
  averageCostBasis: Scalars['Float']['output'];
  averageCostBasisGbp?: Maybe<Scalars['Float']['output']>;
  currency: Scalars['String']['output'];
  fxRateToGbp?: Maybe<Scalars['Float']['output']>;
  id: Scalars['ID']['output'];
  portfolioId: Scalars['ID']['output'];
  shares: Scalars['Float']['output'];
  ticker: Scalars['String']['output'];
};

export type HoldingPerformance = {
  __typename?: 'HoldingPerformance';
  averageCostBasis: Scalars['Float']['output'];
  costBasis: Scalars['Float']['output'];
  currency: Scalars['String']['output'];
  currentPrice?: Maybe<Scalars['Float']['output']>;
  dayChange?: Maybe<Scalars['Float']['output']>;
  dayChangePct?: Maybe<Scalars['Float']['output']>;
  marketValue?: Maybe<Scalars['Float']['output']>;
  portfolioWeightPct?: Maybe<Scalars['Float']['output']>;
  shares: Scalars['Float']['output'];
  ticker: Scalars['String']['output'];
  unrealisedPl?: Maybe<Scalars['Float']['output']>;
  unrealisedPlPct?: Maybe<Scalars['Float']['output']>;
};

export type Portfolio = {
  __typename?: 'Portfolio';
  benchmark: BenchmarkComparison;
  cashFlows: Array<CashFlow>;
  createdAt: Scalars['DateTime']['output'];
  description?: Maybe<Scalars['String']['output']>;
  holdings: Array<Holding>;
  id: Scalars['ID']['output'];
  name: Scalars['String']['output'];
  performance: PortfolioPerformance;
  transactions: Array<Transaction>;
  updatedAt: Scalars['DateTime']['output'];
};

export type PortfolioBenchmarkArgs = {
  benchmark?: Scalars['String']['input'];
  endDate?: InputMaybe<Scalars['Date']['input']>;
  startDate?: InputMaybe<Scalars['Date']['input']>;
};

export type PortfolioPerformanceArgs = {
  endDate?: InputMaybe<Scalars['Date']['input']>;
  startDate?: InputMaybe<Scalars['Date']['input']>;
};

export type PortfolioPerformance = {
  __typename?: 'PortfolioPerformance';
  calculatedAt: Scalars['DateTime']['output'];
  dataQuality: Scalars['String']['output'];
  dayChange?: Maybe<Scalars['Float']['output']>;
  dayChangePct?: Maybe<Scalars['Float']['output']>;
  freeCashBalance: Scalars['Float']['output'];
  holdings: Array<HoldingPerformance>;
  portfolioId: Scalars['ID']['output'];
  portfolioName: Scalars['String']['output'];
  totalCostBasis: Scalars['Float']['output'];
  totalHoldings: Scalars['Int']['output'];
  totalMarketValue?: Maybe<Scalars['Float']['output']>;
  totalUnrealisedPl?: Maybe<Scalars['Float']['output']>;
  totalUnrealisedPlPct?: Maybe<Scalars['Float']['output']>;
  twr?: Maybe<Scalars['Float']['output']>;
  twrAnnualised?: Maybe<Scalars['Float']['output']>;
  twrEndDate?: Maybe<Scalars['Date']['output']>;
  twrMethodology: Scalars['String']['output'];
  twrStartDate?: Maybe<Scalars['Date']['output']>;
};

export type Query = {
  __typename?: 'Query';
  marketQuote: Quote;
  portfolio?: Maybe<Portfolio>;
  portfolios: Array<Portfolio>;
};

export type QueryMarketQuoteArgs = {
  ticker: Scalars['String']['input'];
};

export type QueryPortfolioArgs = {
  id: Scalars['ID']['input'];
};

export type Quote = {
  __typename?: 'Quote';
  change?: Maybe<Scalars['Float']['output']>;
  changePct?: Maybe<Scalars['Float']['output']>;
  currency?: Maybe<Scalars['String']['output']>;
  exchange?: Maybe<Scalars['String']['output']>;
  previousClose?: Maybe<Scalars['Float']['output']>;
  price?: Maybe<Scalars['Float']['output']>;
  ticker: Scalars['String']['output'];
  timestamp?: Maybe<Scalars['DateTime']['output']>;
  volume?: Maybe<Scalars['Int']['output']>;
};

export type Subscription = {
  __typename?: 'Subscription';
  marketQuote: Quote;
};

export type SubscriptionMarketQuoteArgs = {
  ticker: Scalars['String']['input'];
};

export type Transaction = {
  __typename?: 'Transaction';
  date: Scalars['Date']['output'];
  id: Scalars['ID']['output'];
  pricePerShare: Scalars['Float']['output'];
  shares: Scalars['Float']['output'];
  ticker: Scalars['String']['output'];
  totalAmount: Scalars['Float']['output'];
  totalAmountGbp?: Maybe<Scalars['Float']['output']>;
  type: TransactionType;
};

export enum TransactionType {
  Buy = 'BUY',
  Sell = 'SELL',
}

export type MarketQuoteSubscriptionVariables = Exact<{
  ticker: Scalars['String']['input'];
}>;

export type MarketQuoteSubscription = {
  __typename?: 'Subscription';
  marketQuote: {
    __typename?: 'Quote';
    ticker: string;
    price?: number | null;
    change?: number | null;
    changePct?: number | null;
    previousClose?: number | null;
    timestamp?: string | null;
  };
};

export type PortfolioDetailQueryVariables = Exact<{
  id: Scalars['ID']['input'];
}>;

export type PortfolioDetailQuery = {
  __typename?: 'Query';
  portfolio?: {
    __typename?: 'Portfolio';
    id: string;
    name: string;
    performance: {
      __typename?: 'PortfolioPerformance';
      portfolioId: string;
      portfolioName: string;
      totalMarketValue?: number | null;
      totalUnrealisedPl?: number | null;
      totalUnrealisedPlPct?: number | null;
      dayChange?: number | null;
      dayChangePct?: number | null;
      twr?: number | null;
      twrAnnualised?: number | null;
      twrStartDate?: string | null;
      twrEndDate?: string | null;
      twrMethodology: string;
      freeCashBalance: number;
      dataQuality: string;
      totalHoldings: number;
      calculatedAt: string;
      holdings: Array<{
        __typename?: 'HoldingPerformance';
        ticker: string;
        shares: number;
        averageCostBasis: number;
        currentPrice?: number | null;
        currency: string;
        marketValue?: number | null;
        costBasis: number;
        unrealisedPl?: number | null;
        unrealisedPlPct?: number | null;
        dayChange?: number | null;
        dayChangePct?: number | null;
        portfolioWeightPct?: number | null;
      }>;
    };
  } | null;
};
