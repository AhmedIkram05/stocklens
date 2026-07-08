import { apiService, api } from './api';
import { emit } from './eventBus';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Portfolio {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
}

export interface CreatePortfolio {
  name: string;
  description?: string;
}

export interface UpdatePortfolio {
  name?: string;
  description?: string;
}

export interface Holding {
  id: string;
  portfolio_id: string;
  ticker: string;
  shares: number;
  average_cost_basis: number;
  created_at: string;
  updated_at: string;
}

export interface CreateHolding {
  ticker: string;
  shares: number;
  average_cost_basis: number;
}

export interface UpdateHolding {
  shares?: number;
  average_cost_basis?: number;
}

export interface Transaction {
  id: string;
  portfolio_id: string;
  ticker: string;
  shares: number;
  price_per_share: number;
  total_amount: number;
  type: 'BUY' | 'SELL';
  transaction_date: string;
  notes?: string;
  created_at: string;
}

export interface CreateTransaction {
  ticker: string;
  shares: number;
  price_per_share: number;
  type: 'BUY' | 'SELL';
  transaction_date?: string;
  notes?: string;
}

export interface CashFlow {
  id: string;
  portfolio_id: string;
  amount: number;
  source: string;
  source_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface CreateCashFlow {
  amount: number;
  source: 'receipt' | 'manual' | 'transfer';
  source_id?: string;
  notes?: string;
}

export interface UpdateCashFlowNotes {
  notes: string;
}

export interface HoldingPerformance {
  ticker: string;
  shares: number;
  average_cost_basis: number;
  current_price: number | null;
  market_value: number | null;
  cost_basis: number;
  unrealised_pl: number | null;
  unrealised_pl_pct: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  portfolio_weight_pct: number | null;
}

export interface PortfolioPerformance {
  portfolio_id: string;
  portfolio_name: string;
  total_market_value: number | null;
  total_cost_basis: number;
  total_unrealised_pl: number | null;
  total_unrealised_pl_pct: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  free_cash_balance: number;
  twr: number | null;
  twr_annualised: number | null;
  twr_start_date: string | null;
  twr_end_date: string | null;
  twr_methodology: string;
  data_quality: string;
  holdings: HoldingPerformance[];
  total_holdings: number;
  calculated_at: string;
}

export interface BenchmarkComparison {
  portfolio_id: string;
  benchmark_ticker: string;
  portfolio_return: number | null;
  benchmark_return: number | null;
  excess_return_alpha: number | null;
  tracking_error: number | null;
  information_ratio: number | null;
  period_start: string;
  period_end: string;
  methodology: string;
  daily_returns_count: number;
  calculated_at: string;
}

// ── Wrapped list response types ───────────────────────────────────────────────

interface WrappedPortfolioList {
  portfolios: Portfolio[];
  total: number;
}

interface WrappedHoldingList {
  holdings: Holding[];
  total: number;
}

interface WrappedTransactionList {
  transactions: Transaction[];
  total: number;
  page: number;
  page_size: number;
}

interface WrappedCashFlowList {
  cash_flows: CashFlow[];
  total: number;
  limit: number;
  offset: number;
}

// ── Service ───────────────────────────────────────────────────────────────────

export const portfolioService = {
  async listPortfolios(): Promise<Portfolio[]> {
    const res = await apiService.get<WrappedPortfolioList>('/portfolios');
    return res.portfolios;
  },

  async getPortfolio(id: string): Promise<Portfolio> {
    return apiService.get<Portfolio>(`/portfolios/${id}`);
  },

  async createPortfolio(data: CreatePortfolio): Promise<Portfolio> {
    const created = await apiService.post<Portfolio>('/portfolios', data);
    emit('historical-updated', { action: 'create' });
    return created;
  },

  async updatePortfolio(id: string, data: UpdatePortfolio): Promise<Portfolio> {
    const updated = await apiService.put<Portfolio>(`/portfolios/${id}`, data);
    emit('historical-updated', { action: 'update' });
    return updated;
  },

  async deletePortfolio(id: string): Promise<void> {
    await apiService.delete<void>(`/portfolios/${id}`);
    emit('historical-updated', { action: 'delete' });
  },

  async listHoldings(portfolioId: string): Promise<Holding[]> {
    const res = await apiService.get<WrappedHoldingList>(`/portfolios/${portfolioId}/holdings`);
    return res.holdings;
  },

  async createHolding(portfolioId: string, data: CreateHolding): Promise<Holding> {
    const created = await apiService.post<Holding>(`/portfolios/${portfolioId}/holdings`, data);
    emit('historical-updated', { action: 'create-holding', portfolioId });
    return created;
  },

  async updateHolding(id: string, data: UpdateHolding): Promise<Holding> {
    const updated = await apiService.put<Holding>(`/holdings/${id}`, data);
    emit('historical-updated', { action: 'update-holding' });
    return updated;
  },

  async deleteHolding(id: string): Promise<void> {
    await apiService.delete<void>(`/holdings/${id}`);
    emit('historical-updated', { action: 'delete-holding' });
  },

  async listTransactions(portfolioId: string, limit = 50, offset = 0): Promise<Transaction[]> {
    const res = await apiService.get<WrappedTransactionList>(
      `/portfolios/${portfolioId}/transactions?limit=${limit}&offset=${offset}`,
    );
    return res.transactions;
  },

  async createTransaction(portfolioId: string, data: CreateTransaction): Promise<Transaction> {
    const created = await apiService.post<Transaction>(`/portfolios/${portfolioId}/transactions`, {
      ticker: data.ticker,
      type: data.type,
      shares: data.shares,
      price_per_share: data.price_per_share,
      transaction_date: data.transaction_date ?? new Date().toISOString().split('T')[0],
      notes: data.notes,
    });
    emit('historical-updated', { action: 'create-transaction', portfolioId });
    return created;
  },

  async listCashFlows(portfolioId: string, limit = 50, offset = 0): Promise<CashFlow[]> {
    const res = await apiService.get<WrappedCashFlowList>(
      `/portfolios/${portfolioId}/cash-flows?limit=${limit}&offset=${offset}`,
    );
    return res.cash_flows;
  },

  async createCashFlow(portfolioId: string, data: CreateCashFlow): Promise<CashFlow> {
    const created = await apiService.post<CashFlow>(`/portfolios/${portfolioId}/cash-flows`, data);
    emit('historical-updated', { action: 'create-cashflow', portfolioId });
    return created;
  },

  async updateCashFlowNotes(portfolioId: string, cfId: string, notes: string): Promise<CashFlow> {
    const updated = await api<CashFlow>(`/portfolios/${portfolioId}/cash-flows/${cfId}`, {
      method: 'PATCH',
      body: { notes },
    });
    emit('historical-updated', { action: 'update-cashflow', portfolioId });
    return updated;
  },

  async getPerformance(portfolioId: string): Promise<PortfolioPerformance> {
    return apiService.get<PortfolioPerformance>(`/portfolio/performance/${portfolioId}`);
  },

  async getBenchmark(portfolioId: string, benchmarkTicker?: string): Promise<BenchmarkComparison> {
    const query = benchmarkTicker ? `?benchmark=${benchmarkTicker}` : '';
    return apiService.get<BenchmarkComparison>(`/portfolio/benchmark/${portfolioId}${query}`);
  },
};
