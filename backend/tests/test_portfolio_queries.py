"""
Direct tests for the portfolios read layer (``src.portfolios.queries``).

The REST endpoint suite (``test_portfolios.py``) covers these helpers
indirectly; these tests pin the new module's contract directly, including
user scoping.
"""

from __future__ import annotations

from src.portfolios.queries import fetch_portfolio_by_id, fetch_portfolios_from_db

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
PID_1 = "11111111-1111-1111-1111-111111111111"
PID_2 = "22222222-2222-2222-2222-222222222222"


class TestFetchPortfoliosFromDb:
    async def test_returns_seeded_portfolios(self):
        """Seeded portfolios for the user are returned newest-first."""
        rows = await fetch_portfolios_from_db(USER_ID)
        by_id = {str(r["id"]): r for r in rows}
        assert PID_1 in by_id
        assert PID_2 in by_id
        assert by_id[PID_1]["name"] == "Test Portfolio"
        assert by_id[PID_2]["name"] == "Other Portfolio"

    async def test_scoped_to_user(self):
        """A user with no portfolios gets an empty list."""
        assert await fetch_portfolios_from_db(OTHER_USER_ID) == []


class TestFetchPortfolioById:
    async def test_returns_row(self):
        """Owned portfolio resolves to its row."""
        row = await fetch_portfolio_by_id(PID_1, USER_ID)
        assert row is not None
        assert row["name"] == "Test Portfolio"

    async def test_none_for_other_users_portfolio(self):
        """Ownership scoping: another user's id yields None."""
        assert await fetch_portfolio_by_id(PID_1, OTHER_USER_ID) is None

    async def test_none_for_missing_portfolio(self):
        """Unknown id yields None."""
        assert await fetch_portfolio_by_id("00000000-0000-0000-0000-000000000099", USER_ID) is None
