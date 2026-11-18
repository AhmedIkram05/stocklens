"""Tests for the ``market_quote`` subscription + 60s poller (Phase 4).

The resolver is called directly (httpx ASGITransport has no WS); full
transport e2e is covered manually in Phase 6.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from graphql.error import GraphQLError

from src.auth.utils import decode_token
from src.graphql import streaming
from src.graphql.schema import Subscription
from src.graphql.streaming import (
    PORTFOLIO_STREAM_ERROR,
    _poller_loop,
    _poller_tick,
    _portfolio_subscribers,
    _symbol_subscribers,
    start_quote_poller,
    stop_quote_poller,
    subscribe_portfolio,
    subscribe_symbol,
    unsubscribe_portfolio,
    unsubscribe_symbol,
)
from src.performance import queries as performance_queries
from src.performance.schemas import PortfolioPerformanceResponse

CANNED_QUOTE = {
    "ticker": "AAPL",
    "price": 200.5,
    "change": 5.0,
    "change_pct": 2.56,
    "previous_close": 195.5,
    "volume": 1000000,
    "currency": "USD",
    "exchange": "NASDAQ",
    "timestamp": "2026-09-07T12:00:00",
}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the refcount registries — resolver tests subscribe too."""
    saved = dict(_symbol_subscribers)
    saved_portfolios = dict(_portfolio_subscribers)
    _symbol_subscribers.clear()
    _portfolio_subscribers.clear()
    try:
        yield
    finally:
        _symbol_subscribers.clear()
        _symbol_subscribers.update(saved)
        _portfolio_subscribers.clear()
        _portfolio_subscribers.update(saved_portfolios)


class _FakePubSub:
    """Records subscribe/unsubscribe; replays canned listen() messages."""

    def __init__(self, messages: list[dict] | None = None):
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False
        self.messages = messages or []

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def aclose(self) -> None:
        self.closed = True

    async def listen(self):
        for message in self.messages:
            yield message


class _FakeRedis:
    def __init__(self, pubsub: _FakePubSub):
        self._pubsub = pubsub
        self.published: list[tuple[str, str]] = []

    def pubsub(self) -> _FakePubSub:
        return self._pubsub

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


def _authed_info(token: str) -> SimpleNamespace:
    return SimpleNamespace(context={"connection_params": {"authToken": token}})


@pytest.fixture
def _ws_token(auth_headers) -> str:
    return auth_headers["Authorization"].removeprefix("Bearer ")


def _patch_ws_redis(pubsub: _FakePubSub):
    """Patch schema-namespace redis + blacklist check (hermetic, no real Redis)."""
    return (
        patch("src.graphql.schema.get_redis", new=AsyncMock(return_value=_FakeRedis(pubsub))),
        patch("src.graphql.schema.is_token_blacklisted", new=AsyncMock(return_value=False)),
    )


async def test_replay_returns_cached_quote_and_subscribes_first(_ws_token) -> None:
    """First yield == last-value replay; pubsub.subscribe precedes the replay read."""
    pubsub = _FakePubSub()  # listen() yields nothing → stream ends after replay
    gen = Subscription().market_quote(_authed_info(_ws_token), "aapl")
    get_redis_patch, blacklist_patch = _patch_ws_redis(pubsub)
    with (
        get_redis_patch,
        blacklist_patch,
        patch(
            "src.graphql.streaming.get_quote",
            new=AsyncMock(return_value=CANNED_QUOTE),
        ) as mock_fetch,
    ):
        first = await anext(gen)
        # Subscribe-before-replay: no tick can fall into the replay/subscribe gap.
        assert pubsub.subscribed == ["quote:stream:AAPL"]
        mock_fetch.assert_awaited_once_with("AAPL")
        assert first.ticker == "AAPL"
        assert first.price == 200.5
        assert first.previous_close == 195.5
        assert first.timestamp == datetime(2026, 9, 7, 12, 0)
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
    assert pubsub.unsubscribed == ["quote:stream:AAPL"]
    assert pubsub.closed
    assert "AAPL" not in _symbol_subscribers  # cleanup drained the refcount


async def test_replay_rejects_invalid_ticker(_ws_token) -> None:
    gen = Subscription().market_quote(_authed_info(_ws_token), "BAD!!")
    with pytest.raises(GraphQLError, match="Invalid ticker"):
        await anext(gen)
    assert _symbol_subscribers == {}


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"connection_params": {}},
        {"connection_params": {"authToken": ""}},
        {"connection_params": {"authToken": "garbage"}},
        {"connection_params": {"authToken": "Bearer garbage"}},
    ],
)
async def test_ws_auth_rejects_missing_or_invalid_token(context) -> None:
    """No yield before auth — invalid/absent token raises, never subscribes."""
    gen = Subscription().market_quote(SimpleNamespace(context=context), "AAPL")
    with pytest.raises(GraphQLError, match="Forbidden"):
        await anext(gen)
    assert _symbol_subscribers == {}


async def test_ws_auth_rejects_blacklisted_token(_ws_token) -> None:
    pubsub = _FakePubSub()
    gen = Subscription().market_quote(_authed_info(_ws_token), "AAPL")
    get_redis_patch, _ = _patch_ws_redis(pubsub)
    with (
        get_redis_patch,
        patch("src.graphql.schema.is_token_blacklisted", new=AsyncMock(return_value=True)),
    ):
        with pytest.raises(GraphQLError, match="Forbidden"):
            await anext(gen)
    assert _symbol_subscribers == {}


async def test_tick_delivery_yields_published_quotes(_ws_token) -> None:
    """Second yield == parsed pub/sub tick; non-message frames ignored."""
    tick = dict(CANNED_QUOTE, price=201.0)
    pubsub = _FakePubSub(
        messages=[
            {"type": "subscribe", "channel": "quote:stream:AAPL"},
            {"type": "message", "channel": "quote:stream:AAPL", "data": json.dumps(tick)},
        ]
    )
    gen = Subscription().market_quote(_authed_info(_ws_token), "AAPL")
    get_redis_patch, blacklist_patch = _patch_ws_redis(pubsub)
    with (
        get_redis_patch,
        blacklist_patch,
        patch(
            "src.graphql.streaming.get_quote",
            new=AsyncMock(return_value=CANNED_QUOTE),
        ),
    ):
        assert (await anext(gen)).price == 200.5  # replay
        assert (await anext(gen)).price == 201.0  # tick (subscribe-ack skipped)
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
    assert pubsub.closed
    assert "AAPL" not in _symbol_subscribers


def test_unsubscribe_refcount() -> None:
    """Two clients on one symbol keep it polled until the last one leaves."""
    subscribe_symbol("AAPL")
    subscribe_symbol("AAPL")
    assert _symbol_subscribers == {"AAPL": 2}
    unsubscribe_symbol("AAPL")
    assert _symbol_subscribers == {"AAPL": 1}
    unsubscribe_symbol("AAPL")
    assert _symbol_subscribers == {}
    unsubscribe_symbol("AAPL")  # unknown symbol: no KeyError, never negative
    assert _symbol_subscribers == {}


async def test_poller_tick_publishes_and_skips_failures() -> None:
    """Failing symbol skipped (no publish); per-tick cost = 1 fetch per symbol."""
    subscribe_symbol("AAPL")
    subscribe_symbol("MSFT")
    msft = dict(CANNED_QUOTE, ticker="MSFT", price=500.0)
    fake = _FakeRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_quote",
            new=AsyncMock(side_effect=[RuntimeError("provider down"), msft]),
        ) as mock_fetch,
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    mock_fetch.assert_awaited()
    assert mock_fetch.await_count == 2
    assert [channel for channel, _ in fake.published] == ["quote:stream:MSFT"]
    assert json.loads(fake.published[0][1])["price"] == 500.0


async def test_poller_tick_timeout_skips_slow_symbol() -> None:
    """A stalled provider fetch must not stall the cadence for other symbols."""

    async def fake_fetch(symbol: str) -> dict:
        if symbol == "SLOW":
            await asyncio.sleep(0.5)
        return dict(CANNED_QUOTE, ticker=symbol)

    subscribe_symbol("SLOW")
    subscribe_symbol("FAST")
    fake = _FakeRedis(_FakePubSub())
    with (
        patch("src.graphql.streaming.get_quote", new=AsyncMock(side_effect=fake_fetch)),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
        patch("src.graphql.streaming.POLL_FETCH_TIMEOUT_SECONDS", 0.01),
    ):
        await _poller_tick()
    assert [channel for channel, _ in fake.published] == ["quote:stream:FAST"]


async def test_poller_tick_no_subscribers_no_redis() -> None:
    """Empty registry → no Redis touch (lifespan-safe before pools ready)."""
    with patch(
        "src.graphql.streaming.get_redis",
        new=AsyncMock(side_effect=AssertionError("must not be called")),
    ):
        await _poller_tick()


async def test_poller_start_stop_idempotent() -> None:
    """Double start → one task; double stop → no error (lifespan-safe)."""
    try:
        await start_quote_poller()
        first = streaming._poller_task
        assert first is not None
        await start_quote_poller()
        assert streaming._poller_task is first
    finally:
        await stop_quote_poller()
    assert streaming._poller_task is None
    await stop_quote_poller()  # no-op, must not raise


async def test_poller_loop_ticks_and_survives_errors() -> None:
    """Loop repeats ticks on cadence and survives a failing tick."""
    calls = 0

    async def flaky_tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")

    with (
        patch("src.graphql.streaming._poller_tick", new=AsyncMock(side_effect=flaky_tick)),
        patch("src.graphql.streaming.POLL_INTERVAL_SECONDS", 0.01),
    ):
        task = asyncio.create_task(_poller_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert calls >= 2


PID = "11111111-1111-1111-1111-111111111111"
OTHER_PID = "22222222-2222-2222-2222-222222222222"


def _canned_valuation(
    market_value: float = 1200.0, total_holdings: int = 0
) -> PortfolioPerformanceResponse:
    return PortfolioPerformanceResponse(
        portfolio_id=PID,
        portfolio_name="Retirement",
        total_market_value=Decimal(str(market_value)),
        total_cost_basis=Decimal("1000"),
        total_unrealised_pl=Decimal("200"),
        total_unrealised_pl_pct=Decimal("20"),
        day_change=Decimal("20"),
        day_change_pct=Decimal("1.7"),
        free_cash_balance=Decimal("0"),
        twr=None,
        twr_annualised=None,
        twr_start_date=None,
        twr_end_date=None,
        twr_methodology="live-valuation",
        holdings=[],
        total_holdings=total_holdings,
        data_quality="complete",
        calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


async def test_portfolio_valuation_replay_and_tick(_ws_token) -> None:
    """First yield == server compute; later yields == parsed pub/sub valuations."""
    uid = decode_token(_ws_token).sub
    channel = f"portfolio:stream:{PID}:{uid}"
    tick = _canned_valuation(1300.0).model_dump(mode="json")
    pubsub = _FakePubSub(
        messages=[
            {"type": "subscribe", "channel": channel},
            {"type": "message", "channel": channel, "data": json.dumps(tick)},
        ]
    )
    gen = Subscription().portfolio_valuation(_authed_info(_ws_token), PID)
    get_redis_patch, blacklist_patch = _patch_ws_redis(pubsub)
    with (
        get_redis_patch,
        blacklist_patch,
        patch(
            "src.graphql.schema.fetch_portfolio_by_id",
            new=AsyncMock(return_value={"id": PID}),
        ),
        patch(
            "src.graphql.schema.get_portfolio_valuation",
            new=AsyncMock(return_value=_canned_valuation(1200.0)),
        ) as mock_valuation,
    ):
        first = await anext(gen)
        assert pubsub.subscribed == [channel]
        # The token's user is what the valuation — and ownership check — run as.
        mock_valuation.assert_awaited_once_with(PID, uid)
        assert float(first.total_market_value) == 1200.0
        second = await anext(gen)
        assert float(second.total_market_value) == 1300.0
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
    assert pubsub.unsubscribed == [channel]
    assert pubsub.closed
    assert (PID, uid) not in _portfolio_subscribers  # cleanup drained the refcount


async def test_portfolio_valuation_terminates_when_ownership_is_lost(_ws_token) -> None:
    """The poller's sentinel ends the stream instead of leaving stale data open."""
    uid = decode_token(_ws_token).sub
    channel = f"portfolio:stream:{PID}:{uid}"
    pubsub = _FakePubSub(
        messages=[
            {
                "type": "message",
                "channel": channel,
                "data": json.dumps({PORTFOLIO_STREAM_ERROR: "Portfolio not found"}),
            }
        ]
    )
    gen = Subscription().portfolio_valuation(_authed_info(_ws_token), PID)
    get_redis_patch, blacklist_patch = _patch_ws_redis(pubsub)
    with (
        get_redis_patch,
        blacklist_patch,
        patch(
            "src.graphql.schema.fetch_portfolio_by_id",
            new=AsyncMock(return_value={"id": PID}),
        ),
        patch(
            "src.graphql.schema.get_portfolio_valuation",
            new=AsyncMock(return_value=_canned_valuation()),
        ),
    ):
        await anext(gen)  # replay
        with pytest.raises(GraphQLError, match="Portfolio not found"):
            await anext(gen)
    assert (PID, uid) not in _portfolio_subscribers


async def test_portfolio_valuation_rejects_non_uuid_id(_ws_token) -> None:
    """A non-UUID id must be rejected before it reaches an asyncpg ::uuid cast."""
    gen = Subscription().portfolio_valuation(_authed_info(_ws_token), "not-a-uuid")
    get_redis_patch, blacklist_patch = _patch_ws_redis(_FakePubSub())
    with get_redis_patch, blacklist_patch:
        with pytest.raises(GraphQLError, match="Invalid portfolio id"):
            await anext(gen)


async def test_portfolio_valuation_rejects_unowned_portfolio(_ws_token) -> None:
    """Ownership is verified before subscribing — no data for other users."""
    gen = Subscription().portfolio_valuation(_authed_info(_ws_token), PID)
    get_redis_patch, blacklist_patch = _patch_ws_redis(_FakePubSub())
    with (
        get_redis_patch,
        blacklist_patch,
        patch(
            "src.graphql.schema.fetch_portfolio_by_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(GraphQLError, match="Forbidden"):
            await anext(gen)
    assert _portfolio_subscribers == {}


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"connection_params": {}},
        {"connection_params": {"authToken": ""}},
        {"connection_params": {"authToken": "garbage"}},
        {"connection_params": {"authToken": "Bearer garbage"}},
    ],
)
async def test_portfolio_valuation_ws_auth_rejects_missing_or_invalid_token(context) -> None:
    gen = Subscription().portfolio_valuation(SimpleNamespace(context=context), "pid-1")
    with pytest.raises(GraphQLError, match="Forbidden"):
        await anext(gen)
    assert _portfolio_subscribers == {}


def test_portfolio_unsubscribe_refcount() -> None:
    subscribe_portfolio(PID, "user-1")
    subscribe_portfolio(PID, "user-1")
    assert _portfolio_subscribers == {(PID, "user-1"): 2}
    unsubscribe_portfolio(PID, "user-1")
    assert _portfolio_subscribers == {(PID, "user-1"): 1}
    unsubscribe_portfolio(PID, "user-1")
    assert _portfolio_subscribers == {}
    unsubscribe_portfolio(PID, "user-1")  # unknown key: no KeyError
    assert _portfolio_subscribers == {}


async def test_poller_tick_publishes_portfolio_valuation() -> None:
    subscribe_portfolio(PID, "user-1")
    fake = _FakeRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_portfolio_valuation",
            new=AsyncMock(return_value=_canned_valuation(1200.0)),
        ),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    assert [channel for channel, _ in fake.published] == [f"portfolio:stream:{PID}:user-1"]
    assert json.loads(fake.published[0][1])["total_market_value"] == 1200.0


async def test_poller_tick_skips_failed_portfolio_but_publishes_others() -> None:
    """One failing valuation must not silence the rest of the tick."""
    subscribe_portfolio(PID, "user-1")
    subscribe_portfolio(OTHER_PID, "user-1")

    async def fake_valuation(portfolio_id: str, user_id: str):
        if portfolio_id == PID:
            raise RuntimeError("db down")
        return _canned_valuation(1300.0)

    fake = _FakeRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_portfolio_valuation",
            new=AsyncMock(side_effect=fake_valuation),
        ),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    assert [channel for channel, _ in fake.published] == [f"portfolio:stream:{OTHER_PID}:user-1"]


async def test_poller_tick_ownership_lost_sends_error_and_drops() -> None:
    subscribe_portfolio(PID, "user-1")
    fake = _FakeRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_portfolio_valuation",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Portfolio not found")),
        ),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    assert fake.published[0][0] == f"portfolio:stream:{PID}:user-1"
    assert PORTFOLIO_STREAM_ERROR in json.loads(fake.published[0][1])
    assert _portfolio_subscribers == {}  # dead subscription no longer polled


async def test_poller_tick_skips_unpriced_valuation() -> None:
    """A provider outage must not publish a zero valuation over a good one."""
    subscribe_portfolio(PID, "user-1")
    unpriced = _canned_valuation(0.0, total_holdings=2).model_copy(
        update={"total_market_value": None}
    )
    fake = _FakeRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_portfolio_valuation",
            new=AsyncMock(return_value=unpriced),
        ),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    assert fake.published == []


async def test_poller_tick_publish_failure_does_not_abort_others() -> None:
    subscribe_portfolio(PID, "user-1")
    subscribe_portfolio(OTHER_PID, "user-1")

    class _FlakyRedis(_FakeRedis):
        async def publish(self, channel: str, payload: str) -> int:
            if channel == f"portfolio:stream:{PID}:user-1":
                raise RuntimeError("redis down")
            return await super().publish(channel, payload)

    fake = _FlakyRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_portfolio_valuation",
            new=AsyncMock(return_value=_canned_valuation(1200.0)),
        ),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    assert [channel for channel, _ in fake.published] == [f"portfolio:stream:{OTHER_PID}:user-1"]


async def test_poller_tick_handles_symbols_and_portfolios() -> None:
    subscribe_symbol("AAPL")
    subscribe_portfolio(PID, "user-1")
    fake = _FakeRedis(_FakePubSub())
    with (
        patch(
            "src.graphql.streaming.get_quote",
            new=AsyncMock(return_value=dict(CANNED_QUOTE)),
        ),
        patch(
            "src.graphql.streaming.get_portfolio_valuation",
            new=AsyncMock(return_value=_canned_valuation(1200.0)),
        ),
        patch("src.graphql.streaming.get_redis", new=AsyncMock(return_value=fake)),
    ):
        await _poller_tick()
    assert {channel for channel, _ in fake.published} == {
        "quote:stream:AAPL",
        f"portfolio:stream:{PID}:user-1",
    }


async def test_get_portfolio_valuation_rejects_non_uuid() -> None:
    with pytest.raises(HTTPException):
        await performance_queries.get_portfolio_valuation("not-a-uuid", "user-1")


async def test_get_portfolio_valuation_rejects_unowned() -> None:
    verify = AsyncMock(return_value=None)
    with patch("src.performance.queries.verify_portfolio_ownership", new=verify):
        with pytest.raises(HTTPException):
            await performance_queries.get_portfolio_valuation(PID, "user-1")
    verify.assert_awaited_once_with(PID, "user-1")


async def test_get_portfolio_valuation_empty_portfolio() -> None:
    verify = AsyncMock(return_value={"id": PID, "name": "Empty"})
    get_holdings = AsyncMock(return_value=[])
    get_cash = AsyncMock(return_value=Decimal("5"))
    with (
        patch("src.performance.queries.verify_portfolio_ownership", new=verify),
        patch("src.performance.queries.get_holdings", new=get_holdings),
        patch("src.performance.queries.get_free_cash_balance", new=get_cash),
    ):
        resp = await performance_queries.get_portfolio_valuation(PID, "user-1")
    verify.assert_awaited_once_with(PID, "user-1")
    get_holdings.assert_awaited_once_with(PID)
    assert resp.portfolio_id == PID
    assert resp.total_holdings == 0
    assert resp.free_cash_balance == Decimal("5")


async def test_get_portfolio_valuation_uses_canonical_id() -> None:
    """UUID casing from the client must not fork reads or registry keys."""
    canonical = PID.upper()
    verify = AsyncMock(return_value={"id": canonical, "name": "P"})
    get_holdings = AsyncMock(return_value=[])
    with (
        patch("src.performance.queries.verify_portfolio_ownership", new=verify),
        patch("src.performance.queries.get_holdings", new=get_holdings),
        patch(
            "src.performance.queries.get_free_cash_balance",
            new=AsyncMock(return_value=Decimal("0")),
        ),
    ):
        resp = await performance_queries.get_portfolio_valuation(PID, "user-1")
    get_holdings.assert_awaited_once_with(canonical)
    assert resp.portfolio_id == canonical
