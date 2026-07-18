"""
Tests for the 7 agent tool endpoints (src.agent.tool_endpoints).

Covers all Round 4 endpoints at /agent prefix:
  - GET  /spending-analysis/{portfolio_id}
  - GET  /ticker-info/{ticker}
  - GET  /market-news
  - GET  /sector-exposure/{portfolio_id}
  - GET  /diversification-score/{portfolio_id}
  - GET  /dividend-insights/{ticker}
  - POST /compare-tickers

Uses the real Postgres test DB with transaction isolation and mocks
yfinance for external data dependencies. Computational logic (month-over-month
deltas, category/diversification/sector math) is asserted against known inputs,
not just happy-path status codes.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.database.connection import connection_ctx

TEST_PORTFOLIO = "11111111-1111-1111-1111-111111111111"


# ── Helpers ────────────────────────────────────────────────────────────────


async def _get_auth_user_id() -> str:
    """Look up the test user created by ``auth_headers`` fixture."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", "test@stocklens.dev")
        return str(row["id"]) if row else ""


async def _create_portfolio_for_auth_user(user_id: str, name: str = "Test Portfolio") -> str:
    """Create a portfolio owned by the auth user and return its UUID string."""
    pid = str(uuid4())
    async with connection_ctx() as conn:
        await conn.execute(
            "INSERT INTO portfolios (id, user_id, name) VALUES ($1::uuid, $2::uuid, $3)",
            pid,
            user_id,
            name,
        )
    return pid


async def _seed_holding(conn, portfolio_id, ticker, shares, cost_gbp):
    await conn.execute(
        "INSERT INTO holdings (portfolio_id, ticker, shares, average_cost_basis, "
        "currency, fx_rate_to_gbp, average_cost_basis_gbp) "
        "VALUES ($1::uuid, $2, $3, $4, 'GBP', 1.0, $5) "
        "ON CONFLICT (portfolio_id, ticker) DO UPDATE SET shares = EXCLUDED.shares",
        portfolio_id,
        ticker,
        Decimal(str(shares)),
        Decimal(str(cost_gbp)),
        Decimal(str(cost_gbp)),
    )


async def _seed_transaction(
    conn, portfolio_id, ticker, ttype, shares, price, txn_date, cat_id=None
):
    total = Decimal(str(shares * price))
    await conn.execute(
        "INSERT INTO transactions "
        "(portfolio_id, ticker, type, shares, price_per_share, total_amount, "
        "currency, fx_rate_to_gbp, total_amount_gbp, transaction_date, spending_category_id) "
        "VALUES ($1::uuid, $2, $3, $4, $5, $6, 'GBP', 1.0, $7, $8::date, $9::uuid)",
        portfolio_id,
        ticker,
        ttype,
        Decimal(str(shares)),
        Decimal(str(price)),
        total,
        total,
        txn_date,
        cat_id,
    )


def _mock_ticker_info(info: dict | None = None) -> MagicMock:
    """Return a mock yfinance Ticker that returns the given info dict."""
    mock = MagicMock()
    mock.info = info or {
        "longName": "Apple Inc",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "longBusinessSummary": "Apple designs, manufactures, and markets smartphones.",
        "marketCap": 2_500_000_000_000,
        "trailingPE": 28.5,
        "forwardPE": 25.0,
        "dividendYield": 0.005,
        "fiftyTwoWeekHigh": 200.0,
        "fiftyTwoWeekLow": 150.0,
        "fullTimeEmployees": 164000,
        "country": "United States",
        "website": "https://www.apple.com",
        "currency": "USD",
        "exchange": "NASDAQ",
        "currentPrice": 180.0,
        "regularMarketChangePercent": 1.5,
        "regularMarketVolume": 50_000_000,
    }
    mock.news = [
        {
            "title": "Apple Reports Record Quarter",
            "publisher": "Financial Times",
            "link": "https://example.com/apple",
            "providerPublishTime": 1720000000,
            "summary": "Apple beat earnings expectations.",
        }
    ]

    class FakeDividends:
        empty = False
        index = ["2024-01-15"]
        iloc = [0.75]

    mock.dividends = FakeDividends()
    return mock


class _FailingTicker:
    """Simulates yfinance raising on every attribute access."""

    @property
    def info(self):
        raise Exception("yf down")

    @property
    def news(self):
        raise Exception("yf down")

    @property
    def dividends(self):
        raise Exception("yf down")


def _raising_yf(*_args, **_kwargs) -> MagicMock:
    """Return a yf mock whose Ticker raises — simulates yfinance failure."""
    yf = MagicMock()
    yf.Ticker.return_value = _FailingTicker()
    return yf


def _news_title(title: str, ts: int = 1720000000) -> dict:
    return {
        "title": title,
        "publisher": "Reuters",
        "link": f"https://example.com/{title}",
        "providerPublishTime": ts,
        "summary": "summary",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 — Spending Analysis
# ═══════════════════════════════════════════════════════════════════════════


class TestSpendingAnalysis:
    async def _setup(self, auth_user_id: str, txns=None):
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            for t in txns or []:
                # t = (ticker, ttype, shares, price, txn_date, cat_id)
                await _seed_transaction(conn, pid, *t)
        return pid

    @pytest.mark.usefixtures("_seed_categories")
    async def test_returns_category_breakdown(self, client, auth_headers):
        auth_user_id = await _get_auth_user_id()
        async with connection_ctx() as conn:
            cat_row = await conn.fetchrow(
                "SELECT id FROM spending_categories WHERE name = $1", "Groceries"
            )
            cat_id = str(cat_row["id"]) if cat_row else None
        pid = await self._setup(
            auth_user_id,
            [
                ("AAPL", "BUY", 10, 150.0, date.today(), cat_id),
                ("MSFT", "BUY", 5, 300.0, date.today(), cat_id),
            ],
        )

        resp = await client.get(f"/agent/spending-analysis/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # 10*150 + 5*300 = 3000
        assert data["total_spent_gbp"] == 3000.0
        assert len(data["categories"]) == 1
        cat = data["categories"][0]
        assert cat["category"] == "Groceries"
        assert cat["category_id"] == cat_id
        assert cat["total_spend_gbp"] == 3000.0
        assert cat["transaction_count"] == 2
        assert cat["pct_of_total"] == 100.0

    @pytest.mark.usefixtures("_seed_categories")
    async def test_month_over_month_matches_seeded_spend(self, client, auth_headers):
        """The N+1 fix: current vs previous month spend per category, exact values."""
        auth_user_id = await _get_auth_user_id()
        async with connection_ctx() as conn:
            cat_row = await conn.fetchrow(
                "SELECT id FROM spending_categories WHERE name = $1", "Groceries"
            )
            cat_id = str(cat_row["id"]) if cat_row else None

        today = date.today()
        first_current = today.replace(day=1)
        prev_month = (first_current - timedelta(days=1)).replace(day=1)
        pid = await self._setup(
            auth_user_id,
            [
                ("AAPL", "BUY", 10, 100.0, first_current, cat_id),  # 1000 this month
                ("MSFT", "BUY", 5, 40.0, first_current, cat_id),  # 200 this month
                ("AAPL", "BUY", 4, 50.0, prev_month, cat_id),  # 200 last month
            ],
        )

        resp = await client.get(f"/agent/spending-analysis/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        mom = resp.json()["month_over_month"]
        assert "Groceries" in mom
        m = mom["Groceries"]
        assert m["current_month_spend_gbp"] == 1200.0  # 1000 + 200
        assert m["previous_month_spend_gbp"] == 200.0
        assert m["change_gbp"] == 1000.0
        assert m["change_pct"] == 500.0  # +500%

    @pytest.mark.usefixtures("_seed_categories")
    async def test_month_over_month_uncategorised(self, client, auth_headers):
        """NULL spending_category_id rows surface under 'Uncategorised'."""
        auth_user_id = await _get_auth_user_id()
        today = date.today()
        first_current = today.replace(day=1)
        prev_month = (first_current - timedelta(days=1)).replace(day=1)
        pid = await self._setup(
            auth_user_id,
            [
                ("AAPL", "BUY", 10, 100.0, first_current, None),  # 1000 this month, uncategorised
                ("MSFT", "BUY", 2, 50.0, prev_month, None),  # 100 last month, uncategorised
            ],
        )

        resp = await client.get(f"/agent/spending-analysis/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        mom = resp.json()["month_over_month"]
        assert "Uncategorised" in mom
        m = mom["Uncategorised"]
        assert m["current_month_spend_gbp"] == 1000.0
        assert m["previous_month_spend_gbp"] == 100.0

    @pytest.mark.usefixtures("_seed_categories")
    async def test_pct_of_total_sums_to_100(self, client, auth_headers):
        auth_user_id = await _get_auth_user_id()
        async with connection_ctx() as conn:
            cats = await conn.fetch(
                "SELECT id, name FROM spending_categories ORDER BY name LIMIT 2"
            )
            cat_a, cat_b = str(cats[0]["id"]), str(cats[1]["id"])
        pid = await self._setup(auth_user_id, [])
        async with connection_ctx() as conn:
            # Seed directly into two categories
            await _seed_transaction(conn, pid, "AAPL", "BUY", 10, 100.0, date.today(), cat_a)
            await _seed_transaction(conn, pid, "MSFT", "BUY", 10, 300.0, date.today(), cat_b)

        resp = await client.get(f"/agent/spending-analysis/{pid}", headers=auth_headers)
        data = resp.json()
        total_pct = sum(c["pct_of_total"] for c in data["categories"])
        assert total_pct == 100.0
        assert data["total_spent_gbp"] == 4000.0

    async def test_ownership_enforced(self, client, auth_headers):
        resp = await client.get(f"/agent/spending-analysis/{TEST_PORTFOLIO}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_requires_auth(self, client):
        resp = await client.get("/agent/spending-analysis/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 401

    async def test_custom_months_param(self, client, auth_headers):
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        old_date = date.today() - timedelta(days=400)
        async with connection_ctx() as conn:
            await _seed_transaction(conn, pid, "AAPL", "BUY", 10, 150.0, old_date)

        resp = await client.get(f"/agent/spending-analysis/{pid}?months=3", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Transaction 400 days ago should not appear in 3-month window
        assert data["total_spent_gbp"] == 0
        assert data["month_over_month"] == {}


# ═══════════════════════════════════════════════════════════════════════════
# 4.2 — Ticker Info
# ═══════════════════════════════════════════════════════════════════════════


class TestTickerInfo:
    @patch("src.agent.tool_endpoints.yf")
    async def test_returns_ticker_info(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.get("/agent/ticker-info/AAPL", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["company_name"] == "Apple Inc"
        assert data["sector"] == "Technology"
        assert data["market_cap"] == 2_500_000_000_000

    @patch("src.agent.tool_endpoints.yf")
    async def test_ticker_normalised_uppercase(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.get("/agent/ticker-info/aapl", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "AAPL"
        mock_yf.Ticker.assert_called_once_with("AAPL")

    @patch("src.agent.tool_endpoints.yf")
    async def test_yfinance_failure_propagates(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _raising_yf().Ticker.return_value
        # ticker_info has no graceful fallback — a yfinance failure must surface,
        # not silently return wrong data. (ASGITransport re-raises the 500 in test env.)
        with pytest.raises(Exception):
            await client.get("/agent/ticker-info/AAPL", headers=auth_headers)

    @patch("src.agent.tool_endpoints.yf")
    async def test_requires_auth(self, mock_yf, client):
        resp = await client.get("/agent/ticker-info/AAPL")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# 4.3 — Market News
# ═══════════════════════════════════════════════════════════════════════════


class TestMarketNews:
    @patch("src.agent.tool_endpoints.yf")
    async def test_returns_news_for_single_ticker(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.get("/agent/market-news?tickers=AAPL", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == ["AAPL"]
        assert len(data["articles"]) > 0
        assert data["articles"][0]["title"] == "Apple Reports Record Quarter"
        assert data["articles"][0]["publisher"] == "Financial Times"

    @patch("src.agent.tool_endpoints.yf")
    async def test_returns_news_for_multiple_tickers(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.get("/agent/market-news?tickers=AAPL,MSFT", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == ["AAPL", "MSFT"]

    @patch("src.agent.tool_endpoints.yf")
    async def test_dedup_and_normalises_tickers(self, mock_yf, client, auth_headers):
        """Duplicate tickers collapsed, and duplicate news titles deduped."""
        mock = MagicMock()
        # Same title from both tickers -> should appear once
        mock.news = [_news_title("Shared Headline"), _news_title("Unique AAPL")]
        mock_yf.Ticker.return_value = mock
        resp = await client.get("/agent/market-news?tickers=aapl,AAPL,msft", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == ["AAPL", "MSFT"]  # sorted unique
        titles = [a["title"] for a in data["articles"]]
        assert titles.count("Shared Headline") == 1

    @patch("src.agent.tool_endpoints.yf")
    async def test_yfinance_failure_still_200(self, mock_yf, client, auth_headers):
        """Graceful degradation: a failing fetch must not 500 the endpoint."""
        mock_yf.Ticker.return_value = _raising_yf().Ticker.return_value
        resp = await client.get("/agent/market-news?tickers=AAPL", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["articles"] == []

    async def test_requires_ticker_param(self, client, auth_headers):
        resp = await client.get("/agent/market-news", headers=auth_headers)
        assert resp.status_code == 422  # missing required query param

    async def test_requires_auth(self, client):
        resp = await client.get("/agent/market-news?tickers=AAPL")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# 4.4 — Sector Exposure
# ═══════════════════════════════════════════════════════════════════════════


class TestSectorExposure:
    @patch("src.agent.tool_endpoints.yf")
    async def test_returns_sector_breakdown(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            await _seed_holding(conn, pid, "AAPL", 10, 180.0)

        resp = await client.get(f"/agent/sector-exposure/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value_gbp"] == 1800.0  # 10 * 180
        assert data["sectors"][0]["sector"] == "Technology"
        assert data["sectors"][0]["value_gbp"] == 1800.0
        assert data["sectors"][0]["allocation_pct"] == 100.0

    @patch("src.agent.tool_endpoints.yf")
    async def test_unknown_sector_fallback(self, mock_yf, client, auth_headers):
        """Ticker with no sector info falls back to 'Unknown' and still sums."""
        mock = MagicMock()
        mock.info = {}  # no sector key
        mock_yf.Ticker.return_value = mock
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            await _seed_holding(conn, pid, "ZZZ", 5, 100.0)

        resp = await client.get(f"/agent/sector-exposure/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value_gbp"] == 500.0
        assert data["sectors"][0]["sector"] == "Unknown"

    async def test_ownership_enforced(self, client, auth_headers):
        resp = await client.get(f"/agent/sector-exposure/{TEST_PORTFOLIO}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_no_holdings_error(self, client, auth_headers):
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        resp = await client.get(f"/agent/sector-exposure/{pid}", headers=auth_headers)
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 4.5 — Diversification Score
# ═══════════════════════════════════════════════════════════════════════════


class TestDiversificationScore:
    @patch("src.agent.tool_endpoints.yf")
    async def test_single_holding_scores_low(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            await _seed_holding(conn, pid, "AAPL", 10, 180.0)

        resp = await client.get(f"/agent/diversification-score/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert 0 <= data["overall_score"] <= 100
        # Single holding => effective_holdings == 1, top exposure 100%
        assert data["total_holdings"] == 1
        assert data["effective_holdings"] == 1.0
        assert data["breakdown"]["top_holding_exposure_pct"] == 100.0
        assert "Consider adding more holdings" in data["recommendations"][0]
        assert "breakdown" in data

    @patch("src.agent.tool_endpoints.yf")
    async def test_multi_holding_scores_higher_and_effective(self, mock_yf, client, auth_headers):
        """Two equal-weighted holdings => effective_holdings 2, lower top exposure."""
        mock_yf.Ticker.return_value = _mock_ticker_info()
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            await _seed_holding(conn, pid, "AAPL", 10, 180.0)
            await _seed_holding(conn, pid, "MSFT", 10, 180.0)

        resp = await client.get(f"/agent/diversification-score/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_holdings"] == 2
        assert data["effective_holdings"] == 2.0
        assert data["breakdown"]["top_holding_exposure_pct"] == 50.0
        # Single holding overall_score (20) < two-holding score
        single = await self._single_score(client, auth_headers)
        assert data["overall_score"] > single

    async def _single_score(self, client, auth_headers) -> float:
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = _mock_ticker_info()
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            await _seed_holding(conn, pid, "AAPL", 10, 180.0)
        with patch("src.agent.tool_endpoints.yf", mock_yf):
            resp = await client.get(f"/agent/diversification-score/{pid}", headers=auth_headers)
        return resp.json()["overall_score"]

    @patch("src.agent.tool_endpoints.yf")
    async def test_zero_value_rejected(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        auth_user_id = await _get_auth_user_id()
        pid = await _create_portfolio_for_auth_user(auth_user_id)
        async with connection_ctx() as conn:
            # Zero shares => total value 0
            await _seed_holding(conn, pid, "AAPL", 0, 180.0)
        resp = await client.get(f"/agent/diversification-score/{pid}", headers=auth_headers)
        assert resp.status_code == 400

    async def test_ownership_enforced(self, client, auth_headers):
        resp = await client.get(
            f"/agent/diversification-score/{TEST_PORTFOLIO}", headers=auth_headers
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 4.6 — Dividend Insights
# ═══════════════════════════════════════════════════════════════════════════


class TestDividendInsights:
    @patch("src.agent.tool_endpoints.yf")
    async def test_returns_dividend_data(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.get("/agent/dividend-insights/KO", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "KO"
        assert data["dividend_yield"] == 0.005
        assert data["last_dividend_value"] == 0.75
        assert data["last_dividend_date"] == "2024-01-15"

    @patch("src.agent.tool_endpoints.yf")
    async def test_yfinance_failure_propagates(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _raising_yf().Ticker.return_value
        # dividend_insights has no graceful fallback — failure must surface.
        with pytest.raises(Exception):
            await client.get("/agent/dividend-insights/KO", headers=auth_headers)

    async def test_requires_auth(self, client):
        resp = await client.get("/agent/dividend-insights/KO")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# 4.7 — Compare Tickers
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareTickers:
    @patch("src.agent.tool_endpoints.yf")
    async def test_compares_tickers(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": ["AAPL", "MSFT"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["comparisons"]) == 2
        assert data["comparisons"][0]["ticker"] == "AAPL"
        assert data["comparisons"][1]["ticker"] == "MSFT"

    @patch("src.agent.tool_endpoints.yf")
    async def test_filters_by_metrics(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": ["AAPL"], "metrics": ["price", "market_cap"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "price" in data["comparisons"][0]
        assert "market_cap" in data["comparisons"][0]
        assert "pe_ratio" not in data["comparisons"][0]

    @patch("src.agent.tool_endpoints.yf")
    async def test_normalises_tickers(self, mock_yf, client, auth_headers):
        mock_yf.Ticker.return_value = _mock_ticker_info()
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": [" aapl ", "Msft"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == ["AAPL", "MSFT"]

    @patch("src.agent.tool_endpoints.yf")
    async def test_partial_failure_returns_errors(self, mock_yf, client, auth_headers):
        """One ticker succeeds, one raises -> 200 with errors list + partial."""
        good = _mock_ticker_info()
        bad = _raising_yf().Ticker.return_value

        def _ticker_side_effect(t):
            return bad if t == "BAD" else good

        mock_yf.Ticker.side_effect = _ticker_side_effect
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": ["AAPL", "BAD"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert len(data["errors"]) == 1
        assert data["comparisons"][0]["ticker"] == "AAPL"

    async def test_invalid_metrics(self, client, auth_headers):
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": ["AAPL"], "metrics": ["invalid_metric"]},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "Unknown metrics" in resp.json()["detail"]

    async def test_empty_tickers(self, client, auth_headers):
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": []},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_too_many_tickers(self, client, auth_headers):
        resp = await client.post(
            "/agent/compare-tickers",
            json={"tickers": [str(i) for i in range(11)]},
            headers=auth_headers,
        )
        assert resp.status_code == 400
