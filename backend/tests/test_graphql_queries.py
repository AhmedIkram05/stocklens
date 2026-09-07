"""
GraphQL query facade tests (Phase 3 — query-only, no subscriptions yet).

Covers auth (401 parity with REST), ownership isolation (null, no leak),
nesting shape parity with REST JSON, the dataloader batch pattern
(3 batched DB reads + 1 batched compute per list query), market_quote,
and error parity (400/404 messages surface verbatim).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import httpx
import pytest_asyncio

# Seeded in conftest — owned by user-1, NOT by the auth_headers user.
OTHER_PID = "11111111-1111-1111-1111-111111111111"
MISSING_PID = "00000000-0000-0000-0000-000000000000"


@pytest_asyncio.fixture(autouse=True)
async def _serialize_db_access(_test_db):
    """Serialise DB access within each GraphQL test.

    Strawberry resolves sibling fields concurrently, but conftest's
    ``_test_db`` shares ONE asyncpg connection per test and asyncpg allows
    only one in-flight operation per connection (otherwise
    ``InterfaceError: another operation is in progress``). Guarding each
    call with a lock makes concurrent resolvers queue instead of racing.
    Production uses a real pool (no serialization); results are identical.
    """
    from src.database import connection as db_conn_mod

    inner_get = db_conn_mod.get_conn
    lock = asyncio.Lock()

    class _GuardedConnection:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            attr = getattr(self._conn, name)
            if name in {"fetch", "fetchrow", "fetchval", "execute", "executemany"}:

                @wraps(attr)
                async def _guarded(*args, **kwargs):
                    async with lock:
                        return await attr(*args, **kwargs)

                return _guarded
            return attr

    async def _guarded_get_conn():
        return _GuardedConnection(await inner_get())

    db_conn_mod.get_conn = _guarded_get_conn
    try:
        yield
    finally:
        db_conn_mod.get_conn = inner_get


async def _gql(client: httpx.AsyncClient, query: str, auth_headers: dict[str, str] | None = None):
    """POST a GraphQL query; return the raw response."""
    return await client.post("/graphql", json={"query": query}, headers=auth_headers or {})


async def _create_portfolio(client, auth_headers) -> str:
    resp = await client.post(
        "/portfolios", json={"name": "GQL Test Portfolio"}, headers=auth_headers
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _seed_holding(portfolio_id: str, ticker: str = "AAPL") -> None:
    """Insert a holding via SQL with explicit GBP currency (deterministic).

    Seeding via the REST endpoint resolves currency through the instrument
    provider (USD for AAPL when the network is up, GBP fallback otherwise).
    """
    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        await conn.execute(
            "INSERT INTO holdings "
            "(id, portfolio_id, ticker, shares, average_cost_basis, "
            "average_cost_basis_gbp, currency) "
            "VALUES ($1, $2, $3, 10, 150.0, 150.0, 'GBP')",
            str(uuid4()),
            portfolio_id,
            ticker,
        )


async def _seed_txn_and_cash_flow(portfolio_id: str) -> None:
    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        await conn.execute(
            "INSERT INTO transactions "
            "(portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, currency, fx_rate_to_gbp, total_amount_gbp, transaction_date) "
            "VALUES ($1::uuid, 'AAPL', 'BUY', 10, 150.0, 1500.0, 'GBP', 1.0, 1500.0, '2024-06-15')",
            portfolio_id,
        )
        await conn.execute(
            "INSERT INTO cash_flows (portfolio_id, amount, source) "
            "VALUES ($1::uuid, 5000, 'manual')",
            portfolio_id,
        )


def _mock_live_quotes(mocker, price: str = "200.50", previous_close: str = "198.25"):
    """Patch the quote fetch behind fetch_live_quotes (performance path)."""

    async def _fake_get_quote(ticker: str) -> dict:
        return {
            "ticker": ticker,
            "price": Decimal(price),
            "previous_close": Decimal(previous_close),
        }

    return mocker.patch("src.performance.queries.get_quote", side_effect=_fake_get_quote)


class TestGraphQLAuth:
    async def test_no_token_returns_401(self, client: httpx.AsyncClient):
        """Mechanism A: Depends(get_current_user) raises before execution."""
        resp = await _gql(client, "{ __typename }")
        assert resp.status_code == 401

    async def test_garbage_token_returns_401(self, client: httpx.AsyncClient):
        resp = await _gql(client, "{ __typename }", {"Authorization": "Bearer garbage"})
        assert resp.status_code == 401

    async def test_valid_token_returns_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await _gql(client, "{ __typename }", auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["__typename"] == "Query"


class TestOwnership:
    async def test_other_users_portfolio_is_null(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """No existence leak: another user's id resolves to null, no error."""
        resp = await _gql(client, f'{{ portfolio(id: "{OTHER_PID}") {{ id }} }}', auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["portfolio"] is None

    async def test_portfolios_lists_only_owned(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Seeded user-1 portfolios are invisible; created one is listed."""
        pid = await _create_portfolio(client, auth_headers)
        resp = await _gql(client, "{ portfolios { id name } }", auth_headers)
        assert resp.status_code == 200
        rows = resp.json()["data"]["portfolios"]
        assert [r["id"] for r in rows] == [pid]
        assert rows[0]["name"] == "GQL Test Portfolio"

    async def test_missing_portfolio_is_null(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await _gql(client, f'{{ portfolio(id: "{MISSING_PID}") {{ id }} }}', auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["portfolio"] is None


class TestNestingShape:
    async def test_full_nesting_parity(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], mocker
    ):
        """One list query returns children + performance with REST-identical values."""
        _mock_live_quotes(mocker)
        pid = await _create_portfolio(client, auth_headers)
        await _seed_holding(pid)
        await _seed_txn_and_cash_flow(pid)

        resp = await _gql(
            client,
            """{
              portfolios {
                id name
                holdings { ticker shares averageCostBasis currency }
                transactions { ticker type shares pricePerShare totalAmount date }
                cashFlows { amount source }
                performance { totalMarketValue totalCostBasis totalHoldings
                              freeCashBalance twr dataQuality
                              holdings { ticker marketValue costBasis } }
              }
            }""",
            auth_headers,
        )
        assert resp.status_code == 200
        (pf,) = resp.json()["data"]["portfolios"]
        assert pf["id"] == pid

        (h,) = pf["holdings"]
        assert h == {
            "ticker": "AAPL",
            "shares": 10.0,
            "averageCostBasis": 150.0,
            "currency": "GBP",
        }

        (t,) = pf["transactions"]
        assert t["ticker"] == "AAPL"
        assert t["type"] == "BUY"
        assert t["shares"] == 10.0
        assert t["pricePerShare"] == 150.0
        assert t["totalAmount"] == 1500.0
        assert t["date"] == "2024-06-15"

        (cf,) = pf["cashFlows"]
        assert cf == {"amount": 5000.0, "source": "manual"}

        perf = pf["performance"]
        assert perf["totalHoldings"] == 1
        assert perf["totalCostBasis"] == 1500.0
        assert perf["totalMarketValue"] == 2005.0  # 10 × 200.50 live quote
        assert perf["freeCashBalance"] == 3500.0  # 5000 deposit − 1500 BUY
        assert perf["twr"] is None  # no price history → undefined
        assert perf["dataQuality"] == "complete"
        (ph,) = perf["holdings"]
        assert ph["ticker"] == "AAPL"
        assert ph["marketValue"] == 2005.0
        assert ph["costBasis"] == 1500.0

    async def test_single_portfolio_lazy_children(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], mocker
    ):
        """Root portfolio(id) path resolves children lazily (no preload cache)."""
        _mock_live_quotes(mocker)
        pid = await _create_portfolio(client, auth_headers)
        await _seed_holding(pid)

        resp = await _gql(
            client,
            f'{{ portfolio(id: "{pid}") {{ id holdings {{ ticker }} '
            f"performance {{ totalHoldings totalMarketValue }} }}}}",
            auth_headers,
        )
        assert resp.status_code == 200
        pf = resp.json()["data"]["portfolio"]
        assert pf["id"] == pid
        assert pf["holdings"] == [{"ticker": "AAPL"}]
        assert pf["performance"]["totalHoldings"] == 1
        assert pf["performance"]["totalMarketValue"] == 2005.0


class TestBatching:
    async def test_list_query_batches_children_and_compute(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], mocker
    ):
        """N+1 guard: 2 portfolios → each batch helper called once with all pids."""
        from datetime import datetime, timezone
        from decimal import Decimal

        import src.graphql.schema as gql_schema
        from src.performance import queries as queries_mod
        from src.performance.schemas import PortfolioPerformanceResponse

        pid1 = await _create_portfolio(client, auth_headers)
        pid2 = await _create_portfolio(client, auth_headers)
        await _seed_holding(pid1)
        pids = [pid1, pid2]

        def _canned_perf(pid: str) -> PortfolioPerformanceResponse:
            return PortfolioPerformanceResponse(
                portfolio_id=pid,
                portfolio_name="canned",
                total_cost_basis=Decimal(0),
                twr=None,
                twr_methodology="cash-flow-based",
                total_holdings=0,
                free_cash_balance=Decimal(0),
                holdings=[],
                data_quality="complete",
                calculated_at=datetime.now(timezone.utc),
            )

        canned_bulk = mocker.patch.object(
            gql_schema,
            "get_bulk_portfolio_performance",
            new=AsyncMock(
                return_value=type("Bulk", (), {"portfolios": {p: _canned_perf(p) for p in pids}})()
            ),
        )
        spy_holdings = mocker.patch.object(
            gql_schema, "batch_get_holdings", new=AsyncMock(wraps=queries_mod.batch_get_holdings)
        )
        spy_txns = mocker.patch.object(
            gql_schema,
            "batch_get_transactions",
            new=AsyncMock(wraps=queries_mod.batch_get_transactions),
        )
        spy_cfs = mocker.patch.object(
            gql_schema,
            "batch_get_cash_flows",
            new=AsyncMock(wraps=queries_mod.batch_get_cash_flows),
        )
        spy_single = mocker.patch.object(gql_schema, "get_portfolio_performance")

        resp = await _gql(
            client,
            "{ portfolios { id holdings { ticker } performance { totalHoldings } } }",
            auth_headers,
        )
        assert resp.status_code == 200

        # One batched compute + 3 batched reads, each once with ALL pids.
        canned_bulk.assert_called_once_with(pids, ANY)
        spy_holdings.assert_called_once_with(pids)
        spy_txns.assert_called_once_with(pids)
        spy_cfs.assert_called_once_with(pids)
        # Default-dates performance comes from the preload — no single-shot compute.
        spy_single.assert_not_called()

        (first, second) = resp.json()["data"]["portfolios"]
        assert first["holdings"] == [{"ticker": "AAPL"}]
        assert second["holdings"] == []
        assert first["performance"]["totalHoldings"] == 0  # canned preload


class TestMarketQuote:
    async def test_quote_shape_and_uppercase(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], mocker
    ):
        canned = {
            "ticker": "AAPL",
            "price": Decimal("200.50"),
            "change": Decimal("2.25"),
            "change_pct": Decimal("1.14"),
            "previous_close": Decimal("198.25"),
            "volume": 1000000,
            "timestamp": datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
            "currency": "USD",
            "exchange": "NASDAQ",
        }
        mock_get = mocker.patch("src.market.quotes.get_quote", return_value=canned)
        resp = await _gql(
            client,
            '{ marketQuote(ticker: "aapl") { ticker price change changePct '
            "previousClose volume currency exchange timestamp } }",
            auth_headers,
        )
        assert resp.status_code == 200
        q = resp.json()["data"]["marketQuote"]
        assert q["ticker"] == "AAPL"
        assert q["price"] == 200.50
        assert q["change"] == 2.25
        assert q["changePct"] == 1.14
        assert q["previousClose"] == 198.25
        assert q["volume"] == 1000000
        assert q["currency"] == "USD"
        assert q["exchange"] == "NASDAQ"
        assert q["timestamp"].startswith("2026-09-06T12:00:00")
        mock_get.assert_called_once_with("AAPL")  # uppercased

    async def test_invalid_ticker(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        resp = await _gql(client, '{ marketQuote(ticker: "abc def") { price } }', auth_headers)
        assert resp.status_code == 200
        assert "Invalid ticker" in resp.json()["errors"][0]["message"]

    async def test_provider_failure_surfaces_gracefully(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], mocker
    ):
        mocker.patch("src.market.quotes.get_quote", side_effect=RuntimeError("down"))
        resp = await _gql(client, '{ marketQuote(ticker: "AAPL") { price } }', auth_headers)
        assert resp.status_code == 200
        assert "temporarily unavailable" in resp.json()["errors"][0]["message"]


class TestErrors:
    async def test_benchmark_invalid_ticker_parity(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """400 message from REST surfaces verbatim in GraphQL errors."""
        pid = await _create_portfolio(client, auth_headers)
        resp = await _gql(
            client,
            f'{{ portfolio(id: "{pid}") {{ benchmark(benchmark: "TSLA") '
            "{ benchmarkTicker } } }",
            auth_headers,
        )
        assert resp.status_code == 200
        assert "Benchmark must be SPY or QQQ" in resp.json()["errors"][0]["message"]

    async def test_benchmark_missing_portfolio(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await _gql(
            client,
            f'{{ portfolio(id: "{MISSING_PID}") {{ benchmark {{ benchmarkTicker }} }} }}',
            auth_headers,
        )
        assert resp.status_code == 200
        # portfolio null → sub-selection skipped, no error raised
        assert resp.json()["data"]["portfolio"] is None
