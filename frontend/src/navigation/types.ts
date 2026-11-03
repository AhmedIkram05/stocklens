/**
 * Navigation parameter lists.
 *
 * Kept in a dedicated, value-free module so screens import route types without
 * importing AppNavigator — which imports every screen as a value, forming a
 * (type-only) import cycle. AppNavigator re-exports these for compatibility.
 */

/** Root stack navigation parameter list - defines all stack screens and their params */
export type RootStackParamList = {
  /** Onboarding/splash screen shown before authentication */
  Splash: undefined;
  /** Login screen for existing users */
  Login: undefined;
  /** Registration screen for new users */
  SignUp: undefined;
  /** Device lock screen shown when app is locked */
  Lock: undefined;
  /** Main bottom tab navigator (post-auth) */
  MainTabs: undefined;
  /** Calculator screen (future feature, currently unused) */
  Calculator: undefined;
  /** Receipt details modal with projection calculator */
  ReceiptDetails: {
    receiptId: string;
    totalAmount: number;
    date: string;
    image?: string;
    source?: import('../components/ReceiptCard').SourceBadgeKey;
    confidence?: number;
    processingTimeMs?: number;
    merchantName?: string;
    lineItems?: Array<{ name: string; quantity: number; price: number }>;
  };
};

/** Portfolio stack navigation parameter list - defines all portfolio screens */
export type PortfolioStackParamList = {
  PortfolioList: undefined;
  PortfolioDetail: { portfolioId: string; portfolioName?: string };
  CreatePortfolio: undefined;
  Deposit: { portfolioId: string };
  Trade: { portfolioId: string; mode: 'buy' | 'sell' };
  Benchmark: { portfolioId: string; benchmarkTicker?: string };
  SectorExposure: { portfolioId: string };
  DiversificationScore: { portfolioId: string };
};

/** Bottom tab navigation parameter list - defines all tab screens */
export type MainTabParamList = {
  /** Home/dashboard tab showing receipt history */
  Dashboard: undefined;
  /** Portfolio tab for managing investment portfolios */
  Portfolio: undefined;
  /** Scan tab with camera for capturing receipts */
  Scan: undefined;
  /** Summary tab with analytics and insights */
  Summary: undefined;
  /** Settings tab with user preferences */
  Settings: undefined;
};
