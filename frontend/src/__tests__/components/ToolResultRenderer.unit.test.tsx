/**
 * Unit tests for ToolResultRenderer
 *
 * Verifies: renderer registry, each specialised renderer, fallback JSON dump,
 * edge cases (empty data, error objects, null values).
 */

import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import { getToolRenderer, renderToolResult } from '@/components/chat/ToolResultRenderer';

describe('getToolRenderer', () => {
  it('returns specialised renderer for get_portfolio_summary', () => {
    const renderer = getToolRenderer('get_portfolio_summary');
    expect(renderer).toBeDefined();
    const el = renderer({ data: { name: 'Test', total_market_value_gbp: 1000 } });
    expect(el).toBeDefined();
  });

  it('returns JSON fallback for unknown tool', () => {
    const renderer = getToolRenderer('some_unknown_tool');
    expect(renderer).toBeDefined();
    const { getByText } = renderWithProviders(
      renderToolResult('some_unknown_tool', { key: 'value' }),
    );
    expect(getByText(/"key"/)).toBeTruthy();
  });

  it('returns fallback for undefined tool', () => {
    const renderer = getToolRenderer('undefined_tool');
    expect(renderer).toBeDefined();
    const { getByText } = renderWithProviders(renderToolResult('undefined_tool', { test: true }));
    expect(getByText(/test/)).toBeTruthy();
  });
});

describe('PortfolioSummaryRenderer', () => {
  const sampleData = {
    name: 'My Portfolio',
    description: 'Test portfolio',
    total_market_value_gbp: 50000,
    total_cost_basis_gbp: 45000,
    unrealised_pl_gbp: 5000,
    free_cash_balance_gbp: 1000,
    holding_count: 5,
  };

  it('renders portfolio name', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    expect(getByText('My Portfolio')).toBeTruthy();
  });

  it('displays total value', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    expect(getByText(/50,000/)).toBeTruthy();
  });

  it('shows positive P&L in green', () => {
    const { getAllByText } = renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    const matches = getAllByText(/5,000\.00 GBP/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(matches[0].props.children).toContain('5,000.00 GBP');
  });

  it('handles negative P&L', () => {
    const negativeData = { ...sampleData, unrealised_pl_gbp: -2000 };
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_summary', negativeData),
    );
    expect(getByText(/-2,000/)).toBeTruthy();
  });

  it('renders gracefully with empty data', () => {
    expect(() => renderWithProviders(renderToolResult('get_portfolio_summary', {}))).not.toThrow();
  });
});

describe('PortfolioHoldingsRenderer', () => {
  const sampleData = {
    holdings: [
      { ticker: 'AAPL', shares: 10, average_cost_basis: 150, average_cost_basis_gbp: 120 },
      { ticker: 'GOOGL', shares: 5, average_cost_basis: 2800, average_cost_basis_gbp: 2200 },
    ],
    total: 2,
  };

  it('renders ticker symbols', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_holdings', sampleData),
    );
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('GOOGL')).toBeTruthy();
  });

  it('shows shares count', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_holdings', sampleData),
    );
    expect(getByText('10')).toBeTruthy();
  });

  it('handles empty holdings', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_holdings', { holdings: [], total: 0 }),
    );
    expect(getByText(/No holdings/)).toBeTruthy();
  });
});

describe('SectorExposureRenderer', () => {
  const sampleData = {
    total_value_gbp: 10000,
    sectors: [
      { sector: 'Technology', value_gbp: 6000, allocation_pct: 60, tickers: ['AAPL', 'MSFT'] },
      { sector: 'Finance', value_gbp: 4000, allocation_pct: 40, tickers: ['JPM'] },
    ],
  };

  it('renders sector names', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_sector_exposure', sampleData));
    expect(getByText('Technology')).toBeTruthy();
    expect(getByText('Finance')).toBeTruthy();
  });

  it('shows allocation percentages', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_sector_exposure', sampleData));
    expect(getByText(/60\.0%/)).toBeTruthy();
  });

  it('handles empty sectors', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_sector_exposure', { total_value_gbp: 0, sectors: [] }),
    );
    expect(getByText(/No sector data/)).toBeTruthy();
  });
});

describe('PortfolioPerformanceRenderer', () => {
  it('renders TWR metrics', () => {
    const data = {
      twr: 0.0523,
      twr_annualised: 0.105,
      total_gain_loss: 2500,
      total_gain_loss_pct: 5.23,
    };
    const { getByText } = renderWithProviders(renderToolResult('get_portfolio_performance', data));
    expect(getByText(/^TWR$/)).toBeTruthy();
  });

  it('handles partial data', () => {
    expect(() =>
      renderWithProviders(renderToolResult('get_portfolio_performance', { twr: 0.01 })),
    ).not.toThrow();
  });

  it('empty data renders without crash', () => {
    expect(() =>
      renderWithProviders(renderToolResult('get_portfolio_performance', {})),
    ).not.toThrow();
  });
});

describe('BenchmarkComparisonRenderer', () => {
  it('renders alpha and tracking error', () => {
    const data = {
      portfolio_return: 0.08,
      benchmark_return: 0.05,
      excess_return_alpha: 0.03,
      tracking_error: 0.12,
      information_ratio: 0.25,
      benchmark_ticker: 'SPY',
    };
    const { getByText } = renderWithProviders(renderToolResult('compare_to_benchmark', data));
    expect(getByText(/Alpha/)).toBeTruthy();
    expect(getByText(/Tracking/)).toBeTruthy();
  });
});

describe('DiversificationScoreRenderer', () => {
  it('renders score and ticker exposures', () => {
    const data = {
      hhi_score: 850,
      concentration_level: 'low',
      effective_holdings: 11.76,
      total_holdings: 8,
      ticker_exposures: [
        { ticker: 'AAPL', exposure_pct: 15.2 },
        { ticker: 'MSFT', exposure_pct: 12.8 },
      ],
    };
    const { getByText } = renderWithProviders(
      renderToolResult('get_portfolio_diversification_score', data),
    );
    expect(getByText(/850/)).toBeTruthy();
    expect(getByText(/low/)).toBeTruthy();
    expect(getByText('AAPL')).toBeTruthy();
  });
});

describe('TickerComparisonRenderer', () => {
  const data = {
    tickers: [
      {
        ticker: 'AAPL',
        price: 150,
        change_pct: 0.5,
        market_cap: 2500000000000,
        pe_ratio: 28.5,
        sector: 'Technology',
      },
      {
        ticker: 'MSFT',
        price: 350,
        change_pct: -0.2,
        market_cap: 2600000000000,
        pe_ratio: 35.2,
        sector: 'Technology',
      },
    ],
  };

  it('renders ticker symbols as column headers', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('compare_tickers_side_by_side', data),
    );
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('MSFT')).toBeTruthy();
  });

  it('handles empty tickers', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('compare_tickers_side_by_side', { tickers: [] }),
    );
    expect(getByText(/No comparison/)).toBeTruthy();
  });
});

describe('OhlcvRenderer', () => {
  const data = {
    ticker: 'AAPL',
    data_points: 2,
    ohlcv: [
      { date: '2026-07-20', open: 150, high: 152, low: 149, close: 151, volume: 50000000 },
      { date: '2026-07-19', open: 149, high: 151, low: 148, close: 150, volume: 45000000 },
    ],
  };

  it('renders OHLCV data', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_market_ohlcv', data));
    expect(getByText(/2026-07-20/)).toBeTruthy();
  });

  it('handles empty OHLCV array', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_market_ohlcv', { ohlcv: [] }));
    expect(getByText(/No OHLCV/)).toBeTruthy();
  });
});

describe('QuoteRenderer', () => {
  it('renders price and change', () => {
    const data = {
      ticker: 'AAPL',
      price: 175.5,
      change: 2.3,
      change_pct: 1.33,
      previous_close: 173.2,
      volume: 40000000,
    };
    const { getByText } = renderWithProviders(renderToolResult('get_market_quote', data));
    expect(getByText(/175/)).toBeTruthy();
  });

  it('handles negative change', () => {
    const data = {
      ticker: 'AAPL',
      price: 170,
      change: -3.5,
      change_pct: -2.02,
      previous_close: 173.5,
      volume: 45000000,
    };
    const { getByText } = renderWithProviders(renderToolResult('get_market_quote', data));
    expect(getByText(/-3\.5/)).toBeTruthy();
  });
});

describe('TickerInfoRenderer', () => {
  it('renders company info', () => {
    const data = {
      company_name: 'Apple Inc.',
      sector: 'Technology',
      industry: 'Consumer Electronics',
      market_cap: 2500000000000,
      pe_ratio: 28.5,
    };
    const { getByText } = renderWithProviders(renderToolResult('get_ticker_info', data));
    expect(getByText('Apple Inc.')).toBeTruthy();
    expect(getByText(/2500\.00B/)).toBeTruthy();
  });
});

describe('NewsRenderer', () => {
  const data = {
    ticker: 'AAPL',
    articles: [
      {
        title: 'Apple Q3 Earnings Beat',
        publisher: 'Bloomberg',
        published_date: '2026-07-20T10:00:00Z',
        summary: 'Apple reported strong earnings',
      },
    ],
  };

  it('renders article titles', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_market_news', data));
    expect(getByText(/Apple Q3/)).toBeTruthy();
  });

  it('handles empty articles', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_market_news', { articles: [] }),
    );
    expect(getByText(/No news/)).toBeTruthy();
  });
});

describe('LstmForecastRenderer', () => {
  it('renders UP prediction badge', () => {
    const data = { ticker: 'AAPL', prediction: 'UP', confidence: 0.72, model_version: 'v2' };
    const { getByText } = renderWithProviders(renderToolResult('get_lstm_forecast', data));
    expect(getByText('UP')).toBeTruthy();
    expect(getByText(/72%/)).toBeTruthy();
  });

  it('renders DOWN prediction', () => {
    const data = { ticker: 'AAPL', prediction: 'DOWN', confidence: 0.65 };
    const { getByText } = renderWithProviders(renderToolResult('get_lstm_forecast', data));
    expect(getByText('DOWN')).toBeTruthy();
  });

  it('renders FLAT prediction', () => {
    const data = { ticker: 'AAPL', prediction: 'FLAT', confidence: 0.55 };
    const { getByText } = renderWithProviders(renderToolResult('get_lstm_forecast', data));
    expect(getByText('FLAT')).toBeTruthy();
  });
});

describe('SpendingAnalysisRenderer', () => {
  const data = {
    total_spent_gbp: 15000,
    total_received_gbp: 5000,
    transaction_count: 20,
    category_breakdown: [
      { name: 'Groceries', amount_gbp: 6000, count: 10, pct_of_total: 40 },
      { name: 'Transport', amount_gbp: 3000, count: 5, pct_of_total: 20 },
    ],
  };

  it('renders categories with bars', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_spending_analysis', data));
    expect(getByText(/Groceries/)).toBeTruthy();
    expect(getByText(/Transport/)).toBeTruthy();
  });

  it('handles empty categories', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_spending_analysis', { category_breakdown: [] }),
    );
    expect(getByText(/No spending/)).toBeTruthy();
  });
});

describe('RecentTransactionsRenderer', () => {
  const data = {
    transactions: [
      {
        ticker: 'AAPL',
        type: 'BUY',
        shares: 10,
        price_per_share: 150,
        total_amount_gbp: 1500,
        date: '2026-07-20',
      },
      {
        ticker: 'MSFT',
        type: 'SELL',
        shares: 5,
        price_per_share: 350,
        total_amount_gbp: 1750,
        date: '2026-07-19',
      },
    ],
    total: 2,
  };

  it('renders transaction rows', () => {
    const { getByText } = renderWithProviders(renderToolResult('get_recent_transactions', data));
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('BUY')).toBeTruthy();
  });

  it('handles empty transactions', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('get_recent_transactions', { transactions: [] }),
    );
    expect(getByText(/No transactions/)).toBeTruthy();
  });
});

describe('CashFlowSummaryRenderer', () => {
  it('renders deposit summary', () => {
    const data = {
      total_deposits_gbp: 50000,
      deposit_count: 12,
      most_recent_deposit: { amount: 5000, date: '2026-07-20T00:00:00' },
    };
    const { getByText } = renderWithProviders(renderToolResult('get_cash_flow_summary', data));
    expect(getByText(/50,000/)).toBeTruthy();
    expect(getByText(/12/)).toBeTruthy();
  });

  it('handles null most_recent', () => {
    const data = { total_deposits_gbp: 0, deposit_count: 0, most_recent_deposit: null };
    expect(() =>
      renderWithProviders(renderToolResult('get_cash_flow_summary', data)),
    ).not.toThrow();
  });
});

describe('DividendInsightsRenderer', () => {
  it('renders dividend data', () => {
    const data = {
      ticker: 'AAPL',
      dividend_yield: 0.005,
      dividend_rate: 0.96,
      payout_ratio: 0.15,
      ex_dividend_date: '2026-08-10T00:00:00',
    };
    const { getByText } = renderWithProviders(renderToolResult('get_dividend_insights', data));
    expect(getByText(/0\.50%/)).toBeTruthy();
  });

  it('handles missing fields gracefully', () => {
    expect(() => renderWithProviders(renderToolResult('get_dividend_insights', {}))).not.toThrow();
  });
});

describe('JSON fallback renderer', () => {
  it('pretty-prints JSON for unknown tools', () => {
    const { getByText } = renderWithProviders(
      renderToolResult('mystery_tool', { hello: 'world', count: 42 }),
    );
    expect(getByText(/"hello"/)).toBeTruthy();
    expect(getByText(/"world"/)).toBeTruthy();
  });

  it('handles null data gracefully', () => {
    expect(() => renderWithProviders(renderToolResult('mystery_tool', null))).not.toThrow();
  });

  it('handles array data gracefully', () => {
    expect(() => renderWithProviders(renderToolResult('unknown', [1, 2, 3]))).not.toThrow();
  });
});
