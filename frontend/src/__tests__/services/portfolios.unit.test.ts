import { portfolioService } from '@/services/portfolios';
import { emit } from '@/services/eventBus';

jest.mock('@/services/eventBus', () => ({
  emit: jest.fn(),
}));

const mockEmit = emit as jest.MockedFunction<typeof emit>;

const fetchMock = require('jest-fetch-mock');

describe('portfolioService (API)', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('listPortfolios returns array of portfolios', async () => {
    const portfolios = [
      {
        id: '1',
        name: 'Retirement',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
      {
        id: '2',
        name: 'Growth',
        created_at: '2024-02-01T00:00:00Z',
        updated_at: '2024-02-01T00:00:00Z',
      },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ portfolios, total: 2 }), { status: 200 });

    const result = await portfolioService.listPortfolios();

    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Retirement');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios$/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('getPortfolio returns a single portfolio', async () => {
    const portfolio = {
      id: '42',
      name: 'Test',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(portfolio), { status: 200 });

    const result = await portfolioService.getPortfolio('42');

    expect(result).toMatchObject(portfolio);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/42$/),
      expect.any(Object),
    );
  });

  it('createPortfolio sends POST and returns created portfolio', async () => {
    const created = {
      id: '1',
      name: 'New Portfolio',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(created), { status: 201 });

    const result = await portfolioService.createPortfolio({ name: 'New Portfolio' });

    expect(result).toMatchObject(created);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios$/),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"name"'),
      }),
    );
  });

  it('updatePortfolio sends PUT and updates portfolio', async () => {
    const updated = {
      id: '1',
      name: 'Updated Portfolio',
      description: 'Updated description',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-06-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(updated), { status: 200 });

    const result = await portfolioService.updatePortfolio('1', {
      name: 'Updated Portfolio',
      description: 'Updated description',
    });

    expect(result).toMatchObject(updated);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/1$/),
      expect.objectContaining({
        method: 'PUT',
        body: expect.stringContaining('"description"'),
      }),
    );
  });

  it('deletePortfolio sends DELETE and returns void', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    const result = await portfolioService.deletePortfolio('7');

    expect(result).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/7$/),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('createHolding sends POST and returns holding', async () => {
    const holding = {
      id: 'h1',
      portfolio_id: '1',
      ticker: 'AAPL',
      shares: 100,
      average_cost_basis: 150,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(holding), { status: 201 });

    const result = await portfolioService.createHolding('1', {
      ticker: 'AAPL',
      shares: 100,
      average_cost_basis: 150,
    });

    expect(result).toMatchObject(holding);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/1\/holdings$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('updateHolding sends PUT and returns updated holding', async () => {
    const updated = {
      id: 'h1',
      portfolio_id: '1',
      ticker: 'AAPL',
      shares: 200,
      average_cost_basis: 155,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-06-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(updated), { status: 200 });

    const result = await portfolioService.updateHolding('h1', { shares: 200 });

    expect(result).toMatchObject(updated);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/holdings\/h1$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('deleteHolding sends DELETE and returns void', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    const result = await portfolioService.deleteHolding('h1');

    expect(result).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/holdings\/h1$/),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('getPerformance returns PortfolioPerformance with all fields', async () => {
    const perf = {
      portfolio_id: '1',
      portfolio_name: 'Test',
      total_market_value: 50000,
      total_cost_basis: 40000,
      total_unrealised_pl: 10000,
      total_unrealised_pl_pct: 25,
      day_change: 200,
      day_change_pct: 0.4,
      twr: 1.15,
      twr_annualised: 0.12,
      twr_start_date: null,
      twr_end_date: null,
      twr_methodology: 'sub-period',
      data_quality: 'good',
      free_cash_balance: 5000,
      total_holdings: 1,
      calculated_at: '2024-01-01T00:00:00Z',
      holdings: [
        {
          ticker: 'AAPL',
          shares: 100,
          average_cost_basis: 150,
          current_price: 200,
          market_value: 20000,
          cost_basis: 15000,
          unrealised_pl: 5000,
          unrealised_pl_pct: 33.33,
          day_change: 50,
          day_change_pct: 0.25,
          portfolio_weight_pct: 0.4,
        },
      ],
    };
    fetchMock.mockResponseOnce(JSON.stringify(perf), { status: 200 });

    const result = await portfolioService.getPerformance('1');

    expect(result.total_market_value).toBe(50000);
    expect(result.day_change_pct).toBe(0.4);
    expect(result.twr_annualised).toBe(0.12);
    expect(result.free_cash_balance).toBe(5000);
    expect(result.holdings).toHaveLength(1);
    expect(result.holdings[0].ticker).toBe('AAPL');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolio\/performance\/1$/),
      expect.any(Object),
    );
  });

  it('getBenchmark returns BenchmarkComparison with query params', async () => {
    const bench = {
      portfolio_id: '1',
      portfolio_return: 0.12,
      benchmark_ticker: 'SPY',
      benchmark_return: 0.1,
      excess_return_alpha: 0.02,
      tracking_error: 0.05,
      information_ratio: 0.4,
      period_start: '2024-01-01',
      period_end: '2024-12-31',
      methodology: 'daily',
      daily_returns_count: 252,
      calculated_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(bench), { status: 200 });

    const result = await portfolioService.getBenchmark('1', 'SPY');

    expect(result).toMatchObject(bench);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolio\/benchmark\/1\?benchmark=SPY/),
      expect.any(Object),
    );
  });

  it('getBulkPerformance returns Record<string, PortfolioPerformance>', async () => {
    const bulkResponse = {
      portfolios: {
        '1': {
          portfolio_id: '1',
          portfolio_name: 'Test',
          total_market_value: 50000,
          total_cost_basis: 40000,
          total_unrealised_pl: 10000,
          total_unrealised_pl_pct: 25,
          day_change: 200,
          day_change_pct: 0.4,
          twr: 1.15,
          twr_annualised: 0.12,
          twr_start_date: null,
          twr_end_date: null,
          twr_methodology: 'sub-period',
          data_quality: 'good',
          free_cash_balance: 5000,
          total_holdings: 1,
          calculated_at: '2024-01-01T00:00:00Z',
          holdings: [
            {
              ticker: 'AAPL',
              shares: 100,
              average_cost_basis: 150,
              current_price: 200,
              market_value: 20000,
              cost_basis: 15000,
              unrealised_pl: 5000,
              unrealised_pl_pct: 33.33,
              day_change: 50,
              day_change_pct: 0.25,
              portfolio_weight_pct: 0.4,
            },
          ],
        },
      },
    };
    fetchMock.mockResponseOnce(JSON.stringify(bulkResponse), { status: 200 });

    const result = await portfolioService.getBulkPerformance(['1']);

    expect(result['1'].total_market_value).toBe(50000);
    expect(result['1'].holdings).toHaveLength(1);
    expect(result['1'].holdings[0].ticker).toBe('AAPL');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolio\/performance\/bulk\?portfolio_ids=1$/),
      expect.any(Object),
    );
  });

  it('getBulkPerformance with multiple IDs formats URL correctly', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ portfolios: {} }), { status: 200 });

    await portfolioService.getBulkPerformance(['1', '2', '3']);

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolio\/performance\/bulk\?portfolio_ids=1,2,3$/),
      expect.any(Object),
    );
  });

  it('getBenchmark works without optional parameters', async () => {
    const bench = {
      portfolio_id: '1',
      benchmark_ticker: 'SPY',
      portfolio_return: 0.05,
      benchmark_return: 0.04,
      period_start: '2024-01-01',
      period_end: '2024-12-31',
      methodology: 'daily',
      daily_returns_count: 252,
      calculated_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(bench), { status: 200 });

    const result = await portfolioService.getBenchmark('1');

    expect(result).toMatchObject(bench);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/^.*\/portfolio\/benchmark\/1$/),
      expect.any(Object),
    );
  });

  it('createCashFlow sends POST and returns cash flow', async () => {
    const cf = {
      id: 'cf1',
      portfolio_id: '1',
      amount: 5000,
      source: 'manual',
      source_id: null,
      notes: 'Initial deposit',
      created_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(cf), { status: 201 });

    const result = await portfolioService.createCashFlow('1', {
      amount: 5000,
      source: 'manual',
    });

    expect(result).toMatchObject(cf);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/1\/cash-flows$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('updateCashFlowNotes sends PATCH with notes', async () => {
    const updated = {
      id: 'cf1',
      portfolio_id: '1',
      amount: 5000,
      source: 'manual',
      source_id: null,
      notes: 'Updated notes',
      created_at: '2024-01-01T00:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(updated), { status: 200 });

    const result = await portfolioService.updateCashFlowNotes('1', 'cf1', 'Updated notes');

    expect(result).toMatchObject(updated);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/1\/cash-flows\/cf1$/),
      expect.objectContaining({ method: 'PATCH' }),
    );
  });

  it('listHoldings / listTransactions / listCashFlows return typed arrays', async () => {
    const holdings = [
      {
        id: '1',
        portfolio_id: '1',
        ticker: 'AAPL',
        shares: 100,
        average_cost_basis: 150,
        created_at: '',
        updated_at: '',
      },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ holdings, total: 1 }), { status: 200 });
    const h = await portfolioService.listHoldings('1');
    expect(h).toHaveLength(1);
    expect(h[0].ticker).toBe('AAPL');

    const transactions = [
      {
        id: '1',
        portfolio_id: '1',
        ticker: 'AAPL',
        shares: 100,
        price_per_share: 150,
        total_amount: 15000,
        type: 'BUY',
        transaction_date: '2024-01-01',
        created_at: '',
      },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ transactions, total: 1, page: 1, page_size: 50 }), {
      status: 200,
    });
    const t = await portfolioService.listTransactions('1');
    expect(t).toHaveLength(1);
    expect(t[0].type).toBe('BUY');

    const cashFlows = [
      {
        id: '1',
        portfolio_id: '1',
        amount: 5000,
        source: 'manual',
        source_id: null,
        notes: 'Initial deposit',
        created_at: '',
      },
    ];
    fetchMock.mockResponseOnce(
      JSON.stringify({ cash_flows: cashFlows, total: 1, limit: 50, offset: 0 }),
      { status: 200 },
    );
    const cf = await portfolioService.listCashFlows('1');
    expect(cf).toHaveLength(1);
    expect(cf[0].amount).toBe(5000);
  });

  it('createTransaction sends POST with type BUY or SELL', async () => {
    const buyTx = {
      id: '1',
      portfolio_id: '1',
      ticker: 'AAPL',
      shares: 10,
      price_per_share: 200,
      total_amount: 2000,
      type: 'BUY',
      transaction_date: '2024-06-01',
      created_at: '',
    };
    fetchMock.mockResponseOnce(JSON.stringify(buyTx), { status: 201 });
    const buyResult = await portfolioService.createTransaction('1', {
      ticker: 'AAPL',
      shares: 10,
      price_per_share: 200,
      type: 'BUY',
    });
    expect(buyResult.type).toBe('BUY');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/portfolios\/1\/transactions$/),
      expect.objectContaining({ method: 'POST', body: expect.stringContaining('"BUY"') }),
    );

    const sellTx = {
      id: '2',
      portfolio_id: '1',
      ticker: 'AAPL',
      shares: 5,
      price_per_share: 220,
      total_amount: 1100,
      type: 'SELL',
      transaction_date: '2024-06-15',
      created_at: '',
    };
    fetchMock.mockResponseOnce(JSON.stringify(sellTx), { status: 201 });
    const sellResult = await portfolioService.createTransaction('1', {
      ticker: 'AAPL',
      shares: 5,
      price_per_share: 220,
      type: 'SELL',
    });
    expect(sellResult.type).toBe('SELL');
  });
});

describe('portfolioService agent endpoints', () => {
  it('getSectorExposure returns sector exposure data', async () => {
    const data = {
      total_value_gbp: 50000,
      sectors: [
        { sector: 'Technology', value_gbp: 30000, allocation_pct: 60, tickers: ['AAPL'] },
        { sector: 'Finance', value_gbp: 20000, allocation_pct: 40, tickers: ['JPM'] },
      ],
    };
    fetchMock.mockResponseOnce(JSON.stringify(data), { status: 200 });

    const result = await portfolioService.getSectorExposure('1');

    expect(result.sectors).toHaveLength(2);
    expect(result.sectors[0].sector).toBe('Technology');
    expect(result.sectors[0].allocation_pct).toBe(60);
    expect(result.total_value_gbp).toBe(50000);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/sector-exposure\/1$/),
      expect.any(Object),
    );
  });

  it('getSectorExposure handles empty sectors', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ total_value_gbp: 0, sectors: [] }), {
      status: 200,
    });

    const result = await portfolioService.getSectorExposure('1');
    expect(result.sectors).toHaveLength(0);
  });

  it('getDiversificationScore returns score data', async () => {
    const data = {
      overall_score: 85,
      breakdown: {
        holdings_diversity_score: 70,
        holdings_diversity_weight_pct: 50,
        hhi_concentration_score: 30,
        hhi_concentration_weight_pct: 30,
        hhi_raw_value: 1200,
        top_holding_weight_score: 80,
        top_holding_weight_pct: 20,
        top_holding_ticker: 'AAPL',
        top_holding_exposure_pct: 25,
        sector_diversity_score: 65,
        sector_diversity_weight_pct: 20,
        sector_hhi_value: 800,
      },
      total_holdings: 5,
      effective_holdings: 8.33,
      recommendations: [],
    };
    fetchMock.mockResponseOnce(JSON.stringify(data), { status: 200 });

    const result = await portfolioService.getDiversificationScore('1');

    expect(result.overall_score).toBe(85);
    expect(result.total_holdings).toBe(5);
    expect(result.effective_holdings).toBe(8.33);
    expect(result.recommendations).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/diversification-score\/1$/),
      expect.any(Object),
    );
  });

  it('getSpendingAnalysis returns spending analysis data', async () => {
    const data = {
      portfolio_name: 'Test',
      period_months: 12,
      total_spent_gbp: 15000,
      categories: [
        {
          category: 'Groceries',
          category_id: null,
          transaction_count: 10,
          total_spend_gbp: 6000,
          pct_of_total: 40,
        },
        {
          category: 'Transport',
          category_id: null,
          transaction_count: 5,
          total_spend_gbp: 3000,
          pct_of_total: 20,
        },
      ],
      month_over_month: {},
    };
    fetchMock.mockResponseOnce(JSON.stringify(data), { status: 200 });

    const result = await portfolioService.getSpendingAnalysis('1', 12);

    expect(result.total_spent_gbp).toBe(15000);
    expect(result.categories).toHaveLength(2);
    expect(result.categories[0].category).toBe('Groceries');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/spending-analysis\/1\?months=12$/),
      expect.any(Object),
    );
  });
});

describe('portfolioService emit events', () => {
  beforeEach(() => {
    mockEmit.mockClear();
  });

  it('createPortfolio emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: '1', name: 'Test' }), { status: 201 });
    await portfolioService.createPortfolio({ name: 'Test' });
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', { action: 'create' });
  });

  it('updatePortfolio emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: '1', name: 'Updated' }), { status: 200 });
    await portfolioService.updatePortfolio('1', { name: 'Updated' });
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', { action: 'update' });
  });

  it('deletePortfolio emits historical-updated event', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });
    await portfolioService.deletePortfolio('1');
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', { action: 'delete' });
  });

  it('createHolding emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 'h1', ticker: 'AAPL' }), { status: 201 });
    await portfolioService.createHolding('1', {
      ticker: 'AAPL',
      shares: 10,
      average_cost_basis: 150,
    });
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', {
      action: 'create-holding',
      portfolioId: '1',
    });
  });

  it('updateHolding emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 'h1', shares: 200 }), { status: 200 });
    await portfolioService.updateHolding('h1', { shares: 200 });
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', { action: 'update-holding' });
  });

  it('deleteHolding emits historical-updated event', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });
    await portfolioService.deleteHolding('h1');
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', { action: 'delete-holding' });
  });

  it('createTransaction emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 't1', type: 'BUY' }), { status: 201 });
    await portfolioService.createTransaction('1', {
      ticker: 'AAPL',
      shares: 10,
      price_per_share: 150,
      type: 'BUY',
    });
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', {
      action: 'create-transaction',
      portfolioId: '1',
    });
  });

  it('createCashFlow emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 'cf1', amount: 5000 }), { status: 201 });
    await portfolioService.createCashFlow('1', { amount: 5000, source: 'manual' });
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', {
      action: 'create-cashflow',
      portfolioId: '1',
    });
  });

  it('updateCashFlowNotes emits historical-updated event', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ id: 'cf1', notes: 'Updated' }), { status: 200 });
    await portfolioService.updateCashFlowNotes('1', 'cf1', 'Updated');
    expect(mockEmit).toHaveBeenCalledWith('historical-updated', {
      action: 'update-cashflow',
      portfolioId: '1',
    });
  });
});
