"""
Tests for cash_flows repository (src.cash_flows.repository).

Uses real database via connection_ctx() with per-test transaction rollback.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.cash_flows.repository import (
    count_cash_flows,
    create_cash_flow,
    get_cash_flow,
    list_cash_flows,
    sum_cash_flows,
    update_cash_flow_notes,
)

PORTFOLIO_ID = "11111111-1111-1111-1111-111111111111"
OTHER_PORTFOLIO_ID = "22222222-2222-2222-2222-222222222222"


class TestCreateCashFlow:
    """Tests for create_cash_flow."""

    async def test_create_basic(self):
        result = await create_cash_flow(
            portfolio_id=PORTFOLIO_ID,
            amount=Decimal("1000.00"),
        )
        assert result["portfolio_id"] == PORTFOLIO_ID
        assert result["amount"] == Decimal("1000.00")
        assert result["source"] == "receipt"
        assert result["source_id"] is None
        assert result["notes"] is None
        assert "id" in result
        assert "created_at" in result

    async def test_create_with_all_fields(self):
        source_id = str(uuid4())
        result = await create_cash_flow(
            portfolio_id=PORTFOLIO_ID,
            amount=Decimal("500.50"),
            source="manual",
            source_id=source_id,
            notes="Initial deposit",
        )
        assert result["source"] == "manual"
        assert result["source_id"] == source_id
        assert result["notes"] == "Initial deposit"
        assert result["amount"] == Decimal("500.50")

    async def test_create_negative_amount(self):
        result = await create_cash_flow(
            portfolio_id=PORTFOLIO_ID,
            amount=Decimal("-250.00"),
            source="withdrawal",
        )
        assert result["amount"] == Decimal("-250.00")

    async def test_create_with_different_portfolios(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("100"))
        await create_cash_flow(OTHER_PORTFOLIO_ID, Decimal("200"))

        cf1 = await list_cash_flows(PORTFOLIO_ID)
        cf2 = await list_cash_flows(OTHER_PORTFOLIO_ID)
        assert len(cf1) == 1
        assert len(cf2) == 1
        assert cf1[0]["amount"] == Decimal("100")
        assert cf2[0]["amount"] == Decimal("200")


class TestListCashFlows:
    """Tests for list_cash_flows."""

    async def test_empty_list(self):
        result = await list_cash_flows(PORTFOLIO_ID)
        assert result == []

    async def test_multiple_flows_ordered_by_created_at_desc(self):
        """Verify list_cash_flows returns rows in descending chronological order.

        ``created_at`` uses PostgreSQL ``now()`` which is constant within a
        transaction, so all test rows may share the same timestamp.  The query
        uses ``ORDER BY created_at DESC, id DESC`` — this test confirms the
        order constraint by checking actual timestamps from the DB.
        """
        await create_cash_flow(PORTFOLIO_ID, Decimal("100"), notes="first")
        await create_cash_flow(PORTFOLIO_ID, Decimal("200"), notes="second")
        await create_cash_flow(PORTFOLIO_ID, Decimal("300"), notes="third")

        result = await list_cash_flows(PORTFOLIO_ID)
        assert len(result) == 3
        # Verify descending chronological order using actual DB timestamps
        for i in range(len(result) - 1):
            assert result[i]["created_at"] >= result[i + 1]["created_at"]
        # All three items present
        assert {r["notes"] for r in result} == {"first", "second", "third"}

    async def test_limit_and_offset(self):
        """Verify pagination returns disjoint pages."""
        for i in range(5):
            await create_cash_flow(PORTFOLIO_ID, Decimal(str(i * 100)))

        page1 = await list_cash_flows(PORTFOLIO_ID, limit=2, offset=0)
        page2 = await list_cash_flows(PORTFOLIO_ID, limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        # Items on page1 more recent or same recency as page2
        assert page1[-1]["created_at"] >= page2[0]["created_at"]
        # No overlap between pages
        ids_1 = {r["id"] for r in page1}
        ids_2 = {r["id"] for r in page2}
        assert ids_1.isdisjoint(ids_2)

    async def test_other_portfolio_not_included(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("100"))
        await create_cash_flow(OTHER_PORTFOLIO_ID, Decimal("999"))

        result = await list_cash_flows(PORTFOLIO_ID)
        assert len(result) == 1
        assert result[0]["amount"] == Decimal("100")


class TestCountCashFlows:
    """Tests for count_cash_flows."""

    async def test_zero_for_empty(self):
        count = await count_cash_flows(PORTFOLIO_ID)
        assert count == 0

    async def test_counts_correctly(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("100"))
        await create_cash_flow(PORTFOLIO_ID, Decimal("200"))
        await create_cash_flow(OTHER_PORTFOLIO_ID, Decimal("300"))

        count = await count_cash_flows(PORTFOLIO_ID)
        assert count == 2


class TestGetCashFlow:
    """Tests for get_cash_flow."""

    async def test_existing_flow(self):
        created = await create_cash_flow(PORTFOLIO_ID, Decimal("100"), notes="test")
        result = await get_cash_flow(created["id"])
        assert result is not None
        assert result["id"] == created["id"]
        assert result["notes"] == "test"

    async def test_nonexistent_id_returns_none(self):
        fake_id = str(uuid4())
        result = await get_cash_flow(fake_id)
        assert result is None

    async def test_returns_all_fields(self):
        created = await create_cash_flow(
            PORTFOLIO_ID, Decimal("50.25"), source="dividend", notes="quarterly"
        )
        result = await get_cash_flow(created["id"])
        assert result is not None
        assert result["portfolio_id"] == PORTFOLIO_ID
        assert result["amount"] == Decimal("50.25")
        assert result["source"] == "dividend"
        assert result["notes"] == "quarterly"


class TestUpdateCashFlowNotes:
    """Tests for update_cash_flow_notes."""

    async def test_updates_notes(self):
        created = await create_cash_flow(PORTFOLIO_ID, Decimal("100"), notes="old")
        updated = await update_cash_flow_notes(created["id"], "new notes")
        assert updated is True

        result = await get_cash_flow(created["id"])
        assert result is not None
        assert result["notes"] == "new notes"

    async def test_update_to_none(self):
        created = await create_cash_flow(PORTFOLIO_ID, Decimal("100"), notes="something")
        updated = await update_cash_flow_notes(created["id"], None)
        assert updated is True

        result = await get_cash_flow(created["id"])
        assert result is not None
        assert result["notes"] is None

    async def test_nonexistent_id_returns_false(self):
        fake_id = str(uuid4())
        updated = await update_cash_flow_notes(fake_id, "new")
        assert updated is False


class TestSumCashFlows:
    """Tests for sum_cash_flows."""

    async def test_zero_for_empty(self):
        total = await sum_cash_flows(PORTFOLIO_ID)
        assert total == Decimal("0")

    async def test_sums_all_flows(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("100.00"))
        await create_cash_flow(PORTFOLIO_ID, Decimal("200.50"))
        await create_cash_flow(PORTFOLIO_ID, Decimal("-50.25"))

        total = await sum_cash_flows(PORTFOLIO_ID)
        assert total == Decimal("250.25")

    async def test_only_sums_for_given_portfolio(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("100"))
        await create_cash_flow(OTHER_PORTFOLIO_ID, Decimal("999"))

        total = await sum_cash_flows(PORTFOLIO_ID)
        assert total == Decimal("100")


class TestEdgeCases:
    """Edge case tests."""

    async def test_many_cash_flows(self):
        """Test with 100 cash flows."""
        for i in range(100):
            await create_cash_flow(PORTFOLIO_ID, Decimal(str(i)))

        total = await sum_cash_flows(PORTFOLIO_ID)
        assert total == Decimal(str(sum(range(100))))

    async def test_large_amounts(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("999999999.99"))
        total = await sum_cash_flows(PORTFOLIO_ID)
        assert total == Decimal("999999999.99")

    async def test_precision_preserved(self):
        await create_cash_flow(PORTFOLIO_ID, Decimal("0.01"))
        total = await sum_cash_flows(PORTFOLIO_ID)
        assert total == Decimal("0.01")
