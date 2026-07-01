"""
Market data provider — yfinance wrapper with PostgreSQL caching.

Entry points:
    provider.fetch_ohlcv(ticker, start_date, end_date) -> list[dict]
    provider.fetch_quote(ticker) -> dict
    repository.get_ohlcv(ticker, start_date, end_date, limit, offset) -> list[dict]
    repository.get_latest_ohlcv_date(ticker) -> date | None
    repository.upsert_ohlcv(ticker, rows) -> int
"""
