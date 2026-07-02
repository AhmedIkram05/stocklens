import { marketService } from '@/services/market';

const fetchMock = require('jest-fetch-mock');

describe('marketService (API)', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('getOHLCV fetches /market/ohlcv/{ticker} and returns array', async () => {
    const data = [
      {
        date: '2024-01-02',
        open: 150,
        high: 155,
        low: 149,
        close: 154,
        adjusted_close: 153.5,
        volume: 80000000,
      },
    ];
    fetchMock.mockResponseOnce(JSON.stringify({ ticker: 'AAPL', data, total: 1 }), { status: 200 });

    const result = await marketService.getOHLCV('AAPL');

    expect(result).toHaveLength(1);
    expect(result[0].close).toBe(154);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/market\/ohlcv\/AAPL$/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('getOHLCV passes query params when start/end dates provided', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ ticker: 'AAPL', data: [], total: 0 }), {
      status: 200,
    });

    await marketService.getOHLCV('AAPL', '2024-01-01', '2024-01-31');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/market\/ohlcv\/AAPL\?start_date=2024-01-01&end_date=2024-01-31/),
      expect.any(Object),
    );
  });

  it('getQuote returns QuoteData', async () => {
    const quote = {
      ticker: 'AAPL',
      price: 200,
      change: 5,
      change_pct: 2.5,
      previous_close: 195,
      volume: 60000000,
      timestamp: '2024-06-15T16:00:00Z',
    };
    fetchMock.mockResponseOnce(JSON.stringify(quote), { status: 200 });

    const result = await marketService.getQuote('AAPL');

    expect(result).toMatchObject(quote);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/market\/quote\/AAPL$/),
      expect.any(Object),
    );
  });

  it('getOHLCV throws on API error (404 etc)', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ detail: 'Not found' }), { status: 404 });

    await expect(marketService.getOHLCV('INVALID')).rejects.toThrow();
  });
});
