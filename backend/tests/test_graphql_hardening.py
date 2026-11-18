"""GraphQL request hardening: depth, alias, and query-timeout limits.

Each limit is exercised on a tiny schema so the failure path is isolated from
the production resolvers (no DB needed by the logic itself).
"""

from __future__ import annotations

import asyncio

import strawberry
from strawberry.extensions import MaxAliasesLimiter, ParserCache, QueryDepthLimiter

from src.graphql.extensions import QueryTimeout


@strawberry.type
class _Child:
    name: str = "x"


@strawberry.type
class _Parent:
    @strawberry.field
    def child(self) -> _Child:
        return _Child()


@strawberry.type
class _NestedQuery:
    @strawberry.field
    def parent(self) -> _Parent:
        return _Parent()


async def test_depth_limiter_rejects_deep_query() -> None:
    schema = strawberry.Schema(
        query=_NestedQuery,
        extensions=[lambda: QueryDepthLimiter(max_depth=1)],
    )
    result = await schema.execute("{ parent { child { name } } }")
    assert result.errors
    assert "exceeds maximum operation depth" in result.errors[0].message


async def test_depth_limiter_allows_shallow_query() -> None:
    schema = strawberry.Schema(
        query=_NestedQuery,
        extensions=[lambda: QueryDepthLimiter(max_depth=5)],
    )
    result = await schema.execute("{ parent { child { name } } }")
    assert result.errors is None
    assert result.data == {"parent": {"child": {"name": "x"}}}


async def test_alias_limiter_rejects_alias_bomb() -> None:
    schema = strawberry.Schema(
        query=_NestedQuery,
        extensions=[lambda: MaxAliasesLimiter(max_alias_count=1)],
    )
    result = await schema.execute("{ a: parent { child { name } } b: parent { child { name } } }")
    assert result.errors
    assert "aliases found" in result.errors[0].message


async def test_query_timeout_aborts_slow_resolver() -> None:
    @strawberry.type
    class SlowQuery:
        @strawberry.field
        async def slow(self) -> int:
            await asyncio.sleep(0.2)
            return 1

    schema = strawberry.Schema(
        query=SlowQuery,
        extensions=[lambda: QueryTimeout(seconds=0.01)],
    )
    result = await schema.execute("{ slow }")
    assert result.errors
    assert "Query timed out" in result.errors[0].message


async def test_query_timeout_allows_fast_resolver() -> None:
    @strawberry.type
    class FastQuery:
        @strawberry.field
        def fast(self) -> int:
            return 1

    schema = strawberry.Schema(
        query=FastQuery,
        extensions=[lambda: QueryTimeout(seconds=5)],
    )
    result = await schema.execute("{ fast }")
    assert result.errors is None
    assert result.data == {"fast": 1}


def test_production_schema_registers_hardening_extensions() -> None:
    from src.graphql.schema import WebSocketOperationGuard, schema

    extensions = [factory() for factory in schema.extensions]
    assert {type(extension) for extension in extensions} == {
        QueryDepthLimiter,
        MaxAliasesLimiter,
        QueryTimeout,
        ParserCache,
        WebSocketOperationGuard,
    }
    timeout = next(e for e in extensions if isinstance(e, QueryTimeout))
    assert timeout.seconds == 30
