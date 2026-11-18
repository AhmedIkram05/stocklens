"""Execution limits for the GraphQL endpoint.

Depth/alias limits and caches come from Strawberry; there is no built-in query
timeout, so ``QueryTimeout`` supplies one. Subscriptions are deliberately
untouched — they are long-lived streams, not request-scoped work.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from strawberry.extensions import SchemaExtension

from graphql import GraphQLError


class QueryTimeout(SchemaExtension):
    """Abort a query/mutation that runs longer than ``seconds``.

    Wraps the execute step only: ``on_subscribe`` is a separate lifecycle, so
    an open subscription is never killed by a query budget.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    async def on_execute(self) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.seconds
        try:
            async with asyncio.timeout_at(deadline):
                yield
        except TimeoutError:
            # Only claim the timeout when our own deadline expired; a resolver's
            # wait_for/timeout must surface as itself, not "Query timed out".
            if loop.time() >= deadline:
                raise GraphQLError("Query timed out")
            raise
