/**
 * Unit tests for ToolResultRenderer
 *
 * Verifies: renderer registry, each specialised renderer, fallback JSON dump,
 * edge cases (empty data, error objects, null values).
 */

import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import { getToolRenderer, renderToolResult } from '@/components/chat/ToolResultRenderer';

describe('getToolRenderer', () => {
  it('returns specialised renderer for get_portfolio_summary', async () => {
    const renderer = getToolRenderer('get_portfolio_summary');
    expect(renderer).toBeDefined();
    const el = renderer({ data: { name: 'Test', total_market_value_gbp: 1000 } });
    expect(el).toBeDefined();
  });

  it('returns JSON fallback for unknown tool', async () => {
    const renderer = getToolRenderer('some_unknown_tool');
    expect(renderer).toBeDefined();
    const { getByText } = await renderWithProviders(
      renderToolResult('some_unknown_tool', { key: 'value' }),
    );
    expect(getByText(/"key"/)).toBeTruthy();
  });

  it('returns fallback for undefined tool', async () => {
    const renderer = getToolRenderer('undefined_tool');
    expect(renderer).toBeDefined();
    const { getByText } = await renderWithProviders(renderToolResult('undefined_tool', { test: true }));
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

  it('renders portfolio name', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    expect(getByText('My Portfolio')).toBeTruthy();
  });

  it('displays total value', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    expect(getByText(/50,000/)).toBeTruthy();
  });

  it('shows positive P&L in green', async () => {
    const { getAllByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    const matches = getAllByText(/5,000\.00 GBP/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(matches[0].props.children).toContain('5,000.00 GBP');
  });

  it('handles negative P&L', async () => {
    const negativeData = { ...sampleData, unrealised_pl_gbp: -2000 };
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', negativeData),
    );
    expect(getByText(/-2,000/)).toBeTruthy();
  });

  it('renders gracefully with empty data', async () => {
    await renderWithProviders(renderToolResult('get_portfolio_summary', {}));
  });

  it('renders description when present', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', sampleData),
    );
    expect(getByText('Test portfolio')).toBeTruthy();
  });

  it('hides description section when absent', async () => {
    const { queryByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', { name: 'My Portfolio' }),
    );
    expect(queryByText('Test portfolio')).toBeNull();
  });

  it('handles null values gracefully', async () => {
    const { getAllByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', { name: 'Test' }),
    );
    // formatCurrency returns '—' for null values (Total Value, Cost Basis, Cash Balance).
    // P&L uses `?? 0` default, so shows '0.00 GBP' instead of '—'.
    expect(getAllByText('—').length).toBeGreaterThanOrEqual(3);
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

  it('renders ticker symbols', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_holdings', sampleData),
    );
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('GOOGL')).toBeTruthy();
  });

  it('shows shares count', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_holdings', sampleData),
    );
    expect(getByText('10')).toBeTruthy();
  });

  it('handles empty holdings', async () => {
    const { getByText } = await renderWithProviders(
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

  it('renders sector names', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_sector_exposure', sampleData));
    expect(getByText('Technology')).toBeTruthy();
    expect(getByText('Finance')).toBeTruthy();
  });

  it('shows allocation percentages', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_sector_exposure', sampleData));
    expect(getByText(/60\.0%/)).toBeTruthy();
  });

  it('handles empty sectors', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_sector_exposure', { total_value_gbp: 0, sectors: [] }),
    );
    expect(getByText(/No sector data/)).toBeTruthy();
  });
});

describe('PortfolioPerformanceRenderer', () => {
  it('renders TWR metrics', async () => {
    const data = {
      twr: 0.0523,
      twr_annualised: 0.105,
      total_gain_loss: 2500,
      total_gain_loss_pct: 5.23,
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_portfolio_performance', data));
    expect(getByText(/^TWR$/)).toBeTruthy();
  });

  it('handles partial data', async () => {
    await renderWithProviders(renderToolResult('get_portfolio_performance', { twr: 0.01 }));
  });

  it('empty data renders without crash', async () => {
    await renderWithProviders(renderToolResult('get_portfolio_performance', {}));
  });
});

describe('BenchmarkComparisonRenderer', () => {
  it('renders alpha and tracking error', async () => {
    const data = {
      portfolio_return: 0.08,
      benchmark_return: 0.05,
      excess_return_alpha: 0.03,
      tracking_error: 0.12,
      information_ratio: 0.25,
      benchmark_ticker: 'SPY',
    };
    const { getByText } = await renderWithProviders(renderToolResult('compare_to_benchmark', data));
    expect(getByText(/Alpha/)).toBeTruthy();
    expect(getByText(/Tracking/)).toBeTruthy();
  });
});

describe('DiversificationScoreRenderer', () => {
  it('renders score and ticker exposures', async () => {
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
    const { getByText } = await renderWithProviders(
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

  it('renders ticker symbols as column headers', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('compare_tickers_side_by_side', data),
    );
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('MSFT')).toBeTruthy();
  });

  it('handles empty tickers', async () => {
    const { getByText } = await renderWithProviders(
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

  it('renders OHLCV data', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_market_ohlcv', data));
    expect(getByText(/2026-07-20/)).toBeTruthy();
  });

  it('handles empty OHLCV array', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_market_ohlcv', { ohlcv: [] }));
    expect(getByText(/No OHLCV/)).toBeTruthy();
  });
});

describe('QuoteRenderer', () => {
  it('renders price and change', async () => {
    const data = {
      ticker: 'AAPL',
      price: 175.5,
      change: 2.3,
      change_pct: 1.33,
      previous_close: 173.2,
      volume: 40000000,
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_market_quote', data));
    expect(getByText(/175/)).toBeTruthy();
  });

  it('handles negative change', async () => {
    const data = {
      ticker: 'AAPL',
      price: 170,
      change: -3.5,
      change_pct: -2.02,
      previous_close: 173.5,
      volume: 45000000,
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_market_quote', data));
    expect(getByText(/-3\.5/)).toBeTruthy();
  });
});

describe('TickerInfoRenderer', () => {
  it('renders company info', async () => {
    const data = {
      company_name: 'Apple Inc.',
      sector: 'Technology',
      industry: 'Consumer Electronics',
      market_cap: 2500000000000,
      pe_ratio: 28.5,
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_ticker_info', data));
    expect(getByText('Apple Inc.')).toBeTruthy();
    expect(getByText(/2500\.00B/)).toBeTruthy();
  });

  it('renders description when present', async () => {
    const data = {
      company_name: 'Apple Inc.',
      description: 'A technology company that designs consumer electronics.',
      sector: 'Technology',
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_ticker_info', data));
    expect(getByText('A technology company that designs consumer electronics.')).toBeTruthy();
  });

  it('renders country and exchange when present', async () => {
    const data = {
      company_name: 'Apple Inc.',
      sector: 'Technology',
      country: 'US',
      exchange: 'NASDAQ',
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_ticker_info', data));
    expect(getByText('US')).toBeTruthy();
    expect(getByText('NASDAQ')).toBeTruthy();
  });

  it('handles null company_name gracefully', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_ticker_info', { ticker: 'AAPL', sector: 'Technology' }),
    );
    expect(getByText('AAPL')).toBeTruthy();
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

  it('renders article titles', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_market_news', data));
    expect(getByText(/Apple Q3/)).toBeTruthy();
  });

  it('handles empty articles', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_market_news', { articles: [] }),
    );
    expect(getByText(/No news/)).toBeTruthy();
  });
});

describe('LstmForecastRenderer', () => {
  it('renders UP prediction badge', async () => {
    const data = { ticker: 'AAPL', prediction: 'UP', confidence: 0.72, model_version: 'v2' };
    const { getByText } = await renderWithProviders(renderToolResult('get_lstm_forecast', data));
    expect(getByText('UP')).toBeTruthy();
    expect(getByText(/72%/)).toBeTruthy();
  });

  it('renders DOWN prediction', async () => {
    const data = { ticker: 'AAPL', prediction: 'DOWN', confidence: 0.65 };
    const { getByText } = await renderWithProviders(renderToolResult('get_lstm_forecast', data));
    expect(getByText('DOWN')).toBeTruthy();
  });

  it('renders FLAT prediction', async () => {
    const data = { ticker: 'AAPL', prediction: 'FLAT', confidence: 0.55 };
    const { getByText } = await renderWithProviders(renderToolResult('get_lstm_forecast', data));
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

  it('renders categories with bars', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_spending_analysis', data));
    expect(getByText(/Groceries/)).toBeTruthy();
    expect(getByText(/Transport/)).toBeTruthy();
  });

  it('handles empty categories', async () => {
    const { getByText } = await renderWithProviders(
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

  it('renders transaction rows', async () => {
    const { getByText } = await renderWithProviders(renderToolResult('get_recent_transactions', data));
    expect(getByText('AAPL')).toBeTruthy();
    expect(getByText('BUY')).toBeTruthy();
  });

  it('handles empty transactions', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_recent_transactions', { transactions: [] }),
    );
    expect(getByText(/No transactions/)).toBeTruthy();
  });
});

describe('CashFlowSummaryRenderer', () => {
  it('renders deposit summary', async () => {
    const data = {
      total_deposits_gbp: 50000,
      deposit_count: 12,
      most_recent_deposit: { amount: 5000, date: '2026-07-20T00:00:00' },
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_cash_flow_summary', data));
    expect(getByText(/50,000/)).toBeTruthy();
    expect(getByText(/12/)).toBeTruthy();
  });

  it('handles null most_recent', async () => {
    const data = { total_deposits_gbp: 0, deposit_count: 0, most_recent_deposit: null };
    await renderWithProviders(renderToolResult('get_cash_flow_summary', data));
  });

  it('renders last_deposit details when present', async () => {
    const data = {
      total_deposits_gbp: 50000,
      deposit_count: 12,
      most_recent_deposit: { amount: 5000, date: '2026-07-20T00:00:00' },
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_cash_flow_summary', data));
    expect(getByText(/Last Deposit/)).toBeTruthy();
    expect(getByText(/5,000\.00 GBP on 2026-07-20/)).toBeTruthy();
  });

  it('hides last_deposit section when most_recent_deposit is null', async () => {
    const data = { total_deposits_gbp: 0, deposit_count: 0, most_recent_deposit: null };
    const { queryByText } = await renderWithProviders(renderToolResult('get_cash_flow_summary', data));
    expect(queryByText(/Last Deposit/)).toBeNull();
  });
});

describe('DividendInsightsRenderer', () => {
  it('renders dividend data', async () => {
    const data = {
      ticker: 'AAPL',
      dividend_yield: 0.005,
      dividend_rate: 0.96,
      payout_ratio: 0.15,
      ex_dividend_date: '2026-08-10T00:00:00',
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_dividend_insights', data));
    expect(getByText(/0\.50%/)).toBeTruthy();
  });

  it('handles missing fields gracefully', async () => {
    await renderWithProviders(renderToolResult('get_dividend_insights', {}));
  });

  it('renders last_dividend_date when present', async () => {
    const data = {
      ticker: 'AAPL',
      dividend_yield: 0.005,
      dividend_rate: 0.96,
      ex_dividend_date: '2026-08-10',
      last_dividend_date: '2026-07-01',
      last_dividend_value: 0.24,
    };
    const { getByText } = await renderWithProviders(renderToolResult('get_dividend_insights', data));
    expect(getByText(/Last Dividend/)).toBeTruthy();
    expect(getByText(/0\.24/)).toBeTruthy();
  });

  it('hides last_dividend_date section when absent', async () => {
    const data = {
      ticker: 'AAPL',
      dividend_yield: 0.005,
      dividend_rate: 0.96,
    };
    const { queryByText } = await renderWithProviders(renderToolResult('get_dividend_insights', data));
    expect(queryByText(/Last Dividend/)).toBeNull();
  });
});

describe('Tool result numeric coercion', () => {
  it('renders numeric strings from tool output without throwing', async () => {
    await renderWithProviders(
      renderToolResult('get_market_quote', {
        ticker: 'AAPL',
        price: '208.12',
        change: '1.27',
        change_pct: '0.61',
        previous_close: '206.85',
        volume: '1234567',
      }),
    );
  });
});

describe('renderToolResult fallback for _raw / error / string data', () => {
  it('falls back to JSON for string data', async () => {
    // String data is wrapped as { _raw: <string> } and rendered via JsonFallbackRenderer
    // Output looks like: { "_raw": "{\"price\": 208.12}" }
    const { getByText } = await renderWithProviders(
      renderToolResult('get_market_quote', '{"price": 208.12}'),
    );
    expect(getByText(/_raw/)).toBeTruthy();
    expect(getByText(/208.12/)).toBeTruthy();
  });

  it('falls back to JSON for data with only _raw key', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_portfolio_summary', { _raw: 'serialization error' }),
    );
    expect(getByText(/_raw/)).toBeTruthy();
    expect(getByText(/serialization error/)).toBeTruthy();
  });

  it('falls back to JSON for data with only error key', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('get_market_quote', { error: 'No quote data available' }),
    );
    expect(getByText(/error/)).toBeTruthy();
    expect(getByText(/No quote data/)).toBeTruthy();
  });

  it('uses specific renderer when data has normal keys alongside error', async () => {
    // Data has error + price — should use QuoteRenderer, not JSON fallback
    const { getByText } = await renderWithProviders(
      renderToolResult('get_market_quote', { error: 'stale data', price: 100, ticker: 'AAPL' }),
    );
    expect(getByText(/AAPL/)).toBeTruthy();
    expect(getByText(/100\.00/)).toBeTruthy();
  });
});

describe('JSON fallback renderer', () => {
  it('pretty-prints JSON for unknown tools', async () => {
    const { getByText } = await renderWithProviders(
      renderToolResult('mystery_tool', { hello: 'world', count: 42 }),
    );
    expect(getByText(/"hello"/)).toBeTruthy();
    expect(getByText(/"world"/)).toBeTruthy();
  });

  it('handles null data gracefully', async () => {
    await renderWithProviders(renderToolResult('mystery_tool', null));
  });

  it('handles array data gracefully', async () => {
    await renderWithProviders(renderToolResult('unknown', [1, 2, 3]));
  });
});
