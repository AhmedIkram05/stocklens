"""
Market data provider — yfinance wrapper with PostgreSQL caching.

Public API (re-exported from provider and repository):
    get_ohlcv(ticker, start_date, end_date) -> list[OHLCVData]
    get_quote(ticker) -> QuoteResponse
"""
