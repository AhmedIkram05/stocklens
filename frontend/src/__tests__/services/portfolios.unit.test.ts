import { portfolioService } from '@/services/portfolios';

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
