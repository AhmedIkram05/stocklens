import { apiService, api } from './api';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Portfolio {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface CreatePortfolio {
  name: string;
}

export interface UpdatePortfolio {
  name: string;
}

export interface Holding {
  id: number;
  portfolio_id: number;
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
  id: number;
  portfolio_id: number;
  ticker: string;
  shares: number;
  price: number;
  total_amount: number;
  transaction_type: string;
  date: string;
  created_at: string;
}

export interface CreateTransaction {
  ticker: string;
  shares: number;
  price: number;
  transaction_type: 'buy' | 'sell';
  date?: string;
}

export interface CashFlow {
  id: number;
  portfolio_id: number;
  amount: number;
  source: string;
  source_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface CreateCashFlow {
  amount: number;
  source: 'receipt' | 'manual';
  source_id?: string;
  notes?: string;
}

export interface UpdateCashFlowNotes {
  notes: string;
}

export interface HoldingPerformance {
  ticker: string;
  shares: number;
  avg_cost_basis: number;
  current_price: number;
  market_value: number;
  cost_basis: number;
  unrealised_pnl: number;
  unrealised_pnl_pct: number;
  day_change: number;
  day_change_pct: number;
  weight: number;
}

export interface PortfolioPerformance {
  total_value: number;
  total_cost_basis: number;
  total_unrealised_pnl: number;
  total_unrealised_pnl_pct: number;
  total_day_change: number;
  total_day_change_pct: number;
  twr: number;
  annualised_twr: number;
  free_cash_balance: number;
  holdings: HoldingPerformance[];
}

export interface BenchmarkComparison {
  portfolio_twr: number;
  benchmark_ticker: string;
  benchmark_return: number;
  excess_return: number;
  tracking_error: number;
  information_ratio: number;
  daily_returns_count: number;
}

// ── Service ───────────────────────────────────────────────────────────────────

export const portfolioService = {
  async listPortfolios(): Promise<Portfolio[]> {
    return apiService.get<Portfolio[]>('/portfolios');
  },

  async getPortfolio(id: number): Promise<Portfolio> {
    return apiService.get<Portfolio>(`/portfolios/${id}`);
  },

  async createPortfolio(data: CreatePortfolio): Promise<Portfolio> {
    return apiService.post<Portfolio>('/portfolios', data);
  },

  async updatePortfolio(id: number, data: UpdatePortfolio): Promise<Portfolio> {
    return apiService.put<Portfolio>(`/portfolios/${id}`, data);
  },

  async deletePortfolio(id: number): Promise<void> {
    await apiService.delete<void>(`/portfolios/${id}`);
  },

  async listHoldings(portfolioId: number): Promise<Holding[]> {
    return apiService.get<Holding[]>(`/portfolios/${portfolioId}/holdings`);
  },

  async createHolding(portfolioId: number, data: CreateHolding): Promise<Holding> {
    return apiService.post<Holding>(`/portfolios/${portfolioId}/holdings`, data);
  },

  async updateHolding(id: number, data: UpdateHolding): Promise<Holding> {
    return apiService.put<Holding>(`/holdings/${id}`, data);
  },

  async deleteHolding(id: number): Promise<void> {
    await apiService.delete<void>(`/holdings/${id}`);
  },

  async listTransactions(portfolioId: number): Promise<Transaction[]> {
    return apiService.get<Transaction[]>(`/portfolios/${portfolioId}/transactions`);
  },

  async createTransaction(portfolioId: number, data: CreateTransaction): Promise<Transaction> {
    return apiService.post<Transaction>(`/portfolios/${portfolioId}/transactions`, data);
  },

  async listCashFlows(portfolioId: number): Promise<CashFlow[]> {
    return apiService.get<CashFlow[]>(`/portfolios/${portfolioId}/cash-flows`);
  },

  async createCashFlow(portfolioId: number, data: CreateCashFlow): Promise<CashFlow> {
    return apiService.post<CashFlow>(`/portfolios/${portfolioId}/cash-flows`, data);
  },

  async updateCashFlowNotes(portfolioId: number, cfId: number, notes: string): Promise<CashFlow> {
    return api<CashFlow>(`/portfolios/${portfolioId}/cash-flows/${cfId}`, {
      method: 'PATCH',
      body: { notes },
    });
  },

  async getPerformance(portfolioId: number): Promise<PortfolioPerformance> {
    return apiService.get<PortfolioPerformance>(`/portfolio/performance/${portfolioId}`);
  },

  async getBenchmark(portfolioId: number, benchmarkTicker?: string): Promise<BenchmarkComparison> {
    const query = benchmarkTicker ? `?benchmark_ticker=${benchmarkTicker}` : '';
    return apiService.get<BenchmarkComparison>(`/portfolio/benchmark/${portfolioId}${query}`);
  },
};
