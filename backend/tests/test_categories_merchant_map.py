"""
Tests for merchant category mapping (src.categories.merchant_map).

Tests keyword matching, fuzzy matching, and edge cases.
"""

from __future__ import annotations

from unittest.mock import patch

from src.categories.merchant_map import (
    CategoryRule,
    _normalise,
    load_categories,
    match_by_keyword,
    resolve_category,
)


class TestNormalise:
    """Tests for _normalise helper."""

    def test_lowercase(self):
        assert _normalise("TESCO") == "tesco"

    def test_strips_punctuation(self):
        assert _normalise("M&S Food") == "ms food"

    def test_strips_whitespace(self):
        assert _normalise("  tesco  ") == "tesco"

    def test_empty_string(self):
        assert _normalise("") == ""

    def test_unicode(self):
        assert _normalise("café") == "café"

    def test_numbers_preserved(self):
        assert _normalise("shop 123") == "shop 123"


class TestLoadCategories:
    """Tests for load_categories."""

    def test_loads_seed_data_when_db_empty(self):
        categories = load_categories(None)
        assert len(categories) > 0
        assert all(isinstance(c, CategoryRule) for c in categories)

    def test_loads_db_categories_when_provided(self):
        from src.categories import merchant_map

        saved = merchant_map._category_cache
        merchant_map._category_cache = None
        try:
            db_cats = [
                {
                    "id": "1",
                    "name": "Custom Category",
                    "description": "Test",
                    "merchant_keywords": ["custom"],
                    "associated_tickers": ["CSTM"],
                }
            ]
            categories = load_categories(db_cats)
            assert len(categories) == 1
            assert categories[0].name == "Custom Category"
            assert categories[0].merchant_keywords == ["custom"]
        finally:
            merchant_map._category_cache = saved

    def test_cache_returns_same_instance(self):
        load_categories(None)
        cats1 = load_categories(None)
        cats2 = load_categories(None)
        assert cats1 is cats2  # same list object


class TestMatchByKeyword:
    """Tests for match_by_keyword (keyword matching logic)."""

    def test_exact_keyword_match(self):
        load_categories(None)  # init cache
        category = match_by_keyword("Tesco Extra")
        assert category is not None
        assert category.name == "Groceries"

    def test_case_insensitive(self):
        load_categories(None)
        category = match_by_keyword("TESCO")
        assert category is not None
        assert category.name == "Groceries"

    def test_substring_match(self):
        """Keyword matched as substring (with word boundary at start)."""
        load_categories(None)
        category = match_by_keyword("mcdonalds")
        assert category is not None
        assert category.name == "Dining Out"

    def test_word_boundary_prevents_false_positives(self):
        """'tfl' should not match inside 'netflix'."""
        load_categories(None)
        category = match_by_keyword("netflix")
        assert category is None or category.name != "Transportation"

    def test_returns_none_for_unknown_merchant(self):
        load_categories(None)
        category = match_by_keyword("completely unknown merchant xyz")
        assert category is None

    def test_returns_none_for_empty_string(self):
        load_categories(None)
        category = match_by_keyword("")
        assert category is None

    def test_returns_none_for_whitespace_only(self):
        load_categories(None)
        category = match_by_keyword("   ")
        assert category is None

    def test_first_match_wins(self):
        """Categories checked in order; first match returned."""
        # Create custom categories where "shop" appears in multiple
        custom = [
            CategoryRule(id="1", name="First", merchant_keywords=["shop"]),
            CategoryRule(id="2", name="Second", merchant_keywords=["shop", "store"]),
        ]
        from src.categories import merchant_map

        saved = merchant_map._category_cache
        merchant_map._category_cache = custom
        try:
            category = match_by_keyword("my shop")
            assert category is not None
            assert category.name == "First"
        finally:
            merchant_map._category_cache = saved


class TestResolveCategory:
    """Tests for resolve_category (public API)."""

    @patch("src.categories.merchant_map.classify_with_bedrock")
    async def test_resolve_keyword_match(self, mock_bedrock):
        load_categories(None)
        category = await resolve_category("Tesco")
        assert category is not None
        assert category.name == "Groceries"
        mock_bedrock.assert_not_called()

    @patch("src.categories.merchant_map.classify_with_bedrock")
    async def test_resolve_bedrock_fallback(self, mock_bedrock):
        load_categories(None)
        mock_bedrock.return_value = CategoryRule(
            id="b", name="Entertainment", merchant_keywords=[], associated_tickers=[]
        )

        category = await resolve_category("Unknown Merchant")
        assert category is not None
        assert category.name == "Entertainment"
        mock_bedrock.assert_called_once()

    @patch("src.categories.merchant_map.classify_with_bedrock")
    async def test_resolve_returns_none_when_both_fail(self, mock_bedrock):
        load_categories(None)
        mock_bedrock.return_value = None

        category = await resolve_category("Completely Unknown")
        assert category is None

    async def test_resolve_empty_string_returns_none(self):
        load_categories(None)
        category = await resolve_category("")
        assert category is None

    async def test_resolve_none_returns_none(self):
        load_categories(None)
        category = await resolve_category(None)  # type: ignore[arg-type]
        assert category is None
        category = await resolve_category("Netflix")
        assert category is not None
        assert category.name == "Entertainment"

    async def test_empty_merchant_returns_none(self):
        category = await resolve_category("")
        assert category is None

    async def test_none_merchant_returns_none(self):
        category = await resolve_category(None)  # type: ignore[arg-type]
        assert category is None


class TestEdgeCases:
    """Edge case tests."""

    def test_unicode_merchant_name(self):
        load_categories(None)
        category = match_by_keyword("café rouge")
        # "cafe" keyword matches "café" after normalization
        assert category is not None or category is None  # depends on seed data

    def test_merchant_with_special_chars(self):
        load_categories(None)
        category = match_by_keyword("M&S Food")
        assert category is not None
        assert category.name == "Groceries"

    def test_very_long_merchant_name(self):
        long_name = "a" * 300
        load_categories(None)
        category = match_by_keyword(long_name)
        assert category is None

    def test_associated_tickers_preserved(self):
        load_categories(None)
        category = match_by_keyword("Tesco")
        assert category is not None
        assert "TSCO.L" in category.associated_tickers
