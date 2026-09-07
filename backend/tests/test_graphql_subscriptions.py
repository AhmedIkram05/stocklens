"""Tests for the ``market_quote`` subscription + 60s poller (Phase 4).

The resolver is called directly (httpx ASGITransport has no WS); full
transport e2e is covered manually in Phase 6.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from graphql.error import GraphQLError

from src.graphql import streaming
from src.graphql.schema import Subscription
from src.graphql.streaming import (
    _poller_loop,
    _poller_tick,
    _symbol_subscribers,
    start_quote_poller,
    stop_quote_poller,
    subscribe_symbol,
    unsubscribe_symbol,
)

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
    """Snapshot/restore the refcount registry — resolver tests subscribe too."""
    saved = dict(_symbol_subscribers)
    _symbol_subscribers.clear()
    try:
        yield
    finally:
        _symbol_subscribers.clear()
        _symbol_subscribers.update(saved)


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
