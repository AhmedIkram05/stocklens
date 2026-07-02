import { apiService } from './api';

export interface OHLCVData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adjusted_close: number;
  volume: number;
}

export interface QuoteData {
  ticker: string;
  price: number;
  change: number;
  change_pct: number;
  previous_close: number;
  volume: number;
  timestamp: string;
}

interface OHLCVResponse {
  ticker: string;
  data: OHLCVData[];
  total: number;
}

export const marketService = {
  async getOHLCV(ticker: string, startDate?: string, endDate?: string): Promise<OHLCVData[]> {
    const params = new URLSearchParams();
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    const qs = params.toString();
    const endpoint = `/market/ohlcv/${ticker}${qs ? `?${qs}` : ''}`;
    const res = await apiService.get<OHLCVResponse>(endpoint);
    return res.data;
  },

  async getQuote(ticker: string): Promise<QuoteData> {
    return apiService.get<QuoteData>(`/market/quote/${ticker}`);
  },
};
