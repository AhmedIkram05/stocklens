"""
Tests for categories seed data (src.categories.seed).

Tests the SEED_CATEGORIES structure and seed_categories function.
"""

from __future__ import annotations

import json

from src.categories.seed import (
    CATEGORY_NAMES,
    SEED_CATEGORIES,
    get_seed_categories,
    seed_categories,
)


class TestSeedCategoriesStructure:
    """Tests for SEED_CATEGORIES list structure."""

    def test_is_list_of_dicts(self):
        assert isinstance(SEED_CATEGORIES, list)
        assert all(isinstance(c, dict) for c in SEED_CATEGORIES)

    def test_expected_category_count(self):
        # Should have 10 categories (Groceries through Financial Services)
        assert len(SEED_CATEGORIES) == 10

    def test_each_category_has_required_fields(self):
        required = {"name", "description", "merchant_keywords", "associated_tickers"}
        for cat in SEED_CATEGORIES:
            assert set(cat.keys()) == required, f"Category {cat.get('name')} missing fields"

    def test_name_is_string(self):
        for cat in SEED_CATEGORIES:
            assert isinstance(cat["name"], str)
            assert cat["name"]

    def test_description_is_string(self):
        for cat in SEED_CATEGORIES:
            assert isinstance(cat["description"], str)
            assert cat["description"]

    def test_merchant_keywords_is_list_of_strings(self):
        for cat in SEED_CATEGORIES:
            keywords = cat["merchant_keywords"]
            assert isinstance(keywords, list)
            assert all(isinstance(k, str) for k in keywords)
            assert len(keywords) > 0

    def test_associated_tickers_is_list_of_strings(self):
        for cat in SEED_CATEGORIES:
            tickers = cat["associated_tickers"]
            assert isinstance(tickers, list)
            assert all(isinstance(t, str) for t in tickers)
            assert len(tickers) > 0

    def test_no_duplicate_names(self):
        names = [cat["name"] for cat in SEED_CATEGORIES]
        assert len(names) == len(set(names)), "Duplicate category names found"

    def test_category_names_list_matches(self):
        assert CATEGORY_NAMES == [cat["name"] for cat in SEED_CATEGORIES]


class TestGetSeedCategories:
    """Tests for get_seed_categories helper."""

    def test_returns_copy(self):
        cats1 = get_seed_categories()
        cats2 = get_seed_categories()
        assert cats1 is not cats2
        assert cats1 == cats2

    def test_modifying_returned_list_does_not_affect_original(self):
        cats = get_seed_categories()
        cats[0]["name"] = "Modified"
        original = get_seed_categories()
        assert original[0]["name"] != "Modified"


class TestSeedCategoriesFunction:
    """Tests for seed_categories (async DB insert)."""

    async def test_returns_count_of_inserted(self):
        count = await seed_categories()
        assert isinstance(count, int)
        assert count >= 0

    async def test_idempotent_second_call_returns_zero(self):
        await seed_categories()
        count = await seed_categories()
        assert count == 0

    async def test_inserts_all_categories(self):
        from src.database.connection import connection_ctx

        await seed_categories()

        async with connection_ctx() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM spending_categories")
        assert count == len(SEED_CATEGORIES)

    def _parse_jsonb(self, value):
        """Parse JSONB value — asyncpg may return str or decoded list/dict."""
        import json as _json

        return _json.loads(value) if isinstance(value, str) else value

    async def test_stores_merchant_keywords_as_jsonb(self):
        from src.database.connection import connection_ctx

        await seed_categories()

        async with connection_ctx() as conn:
            row = await conn.fetchrow(
                "SELECT merchant_keywords FROM spending_categories WHERE name = 'Groceries'"
            )
        assert row is not None
        keywords = self._parse_jsonb(row["merchant_keywords"])
        assert isinstance(keywords, list)
        assert "tesco" in keywords

    async def test_stores_associated_tickers_as_jsonb(self):
        from src.database.connection import connection_ctx

        await seed_categories()

        async with connection_ctx() as conn:
            row = await conn.fetchrow(
                "SELECT associated_tickers FROM spending_categories WHERE name = 'Groceries'"
            )
        assert row is not None
        tickers = self._parse_jsonb(row["associated_tickers"])
        assert isinstance(tickers, list)
        assert "TSCO.L" in tickers

    async def test_existing_categories_not_duplicated(self):
        from src.database.connection import connection_ctx

        # Insert one seed category manually first
        async with connection_ctx() as conn:
            await conn.execute(
                "INSERT INTO spending_categories (name, description, merchant_keywords, associated_tickers) "
                "VALUES ($1, $2, $3::jsonb, $4::jsonb)",
                "Groceries",
                "Manually pre-inserted",
                json.dumps(["manual"]),
                json.dumps(["MNL"]),
            )

        count = await seed_categories()
        # Should skip Groceries (already exists) and insert remaining 9
        assert count == len(SEED_CATEGORIES) - 1

        async with connection_ctx() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM spending_categories")
        # The manual Groceries + 9 seed inserts = 10 total
        assert total == len(SEED_CATEGORIES)


class TestSpecificCategories:
    """Spot-check specific known categories."""

    def test_groceries_has_expected_keywords(self):
        groceries = next(c for c in SEED_CATEGORIES if c["name"] == "Groceries")
        assert "tesco" in groceries["merchant_keywords"]
        assert "TSCO.L" in groceries["associated_tickers"]

    def test_dining_out_has_expected_keywords(self):
        dining = next(c for c in SEED_CATEGORIES if c["name"] == "Dining Out")
        assert "mcdonald" in dining["merchant_keywords"]
        assert "MCD" in dining["associated_tickers"]

    def test_transportation_has_expected_keywords(self):
        transport = next(c for c in SEED_CATEGORIES if c["name"] == "Transportation")
        assert "tfl" in transport["merchant_keywords"]
        assert "UBER" in transport["associated_tickers"]

    def test_financial_services_has_expected_keywords(self):
        fs = next(c for c in SEED_CATEGORIES if c["name"] == "Financial Services")
        assert "monzo" in fs["merchant_keywords"]
        assert any(t in fs["associated_tickers"] for t in ("PYPL", "V", "MA"))
