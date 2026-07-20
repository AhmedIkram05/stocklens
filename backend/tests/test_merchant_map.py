"""
Tests for categories/merchant_map.py — merchant-to-category resolution.

Covers keyword matching, sanitisation, prompt building, and category loading.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.categories.merchant_map import (
    CategoryRule,
    _build_bedrock_prompt,
    _normalise,
    _sanitise_merchant,
    get_categories,
    load_categories,
    match_by_keyword,
    resolve_category,
)


class TestNormalise:
    """Tests for _normalise — text cleaning utility."""

    def test_lowercase_and_strip_punctuation(self):
        assert _normalise("Tesco PLC!") == "tesco plc"

    def test_removes_special_chars(self):
        assert _normalise("M&S Food") == "ms food"

    def test_handles_empty_string(self):
        assert _normalise("") == ""

    def test_handles_whitespace_only(self):
        assert _normalise("   ") == ""


class TestSanitiseMerchant:
    """Tests for _sanitise_merchant — input sanitisation."""

    def test_strips_control_characters(self):
        result = _sanitise_merchant("Test\x00Merchant\x1fName")
        assert result == "TestMerchantName"

    def test_truncates_long_names(self):
        long_name = "A" * 300
        result = _sanitise_merchant(long_name)
        assert len(result) <= 256

    def test_passes_through_normal_names(self):
        result = _sanitise_merchant("Tesco Stores Ltd")
        assert result == "Tesco Stores Ltd"


class TestBuildBedrockPrompt:
    """Tests for _build_bedrock_prompt — prompt construction."""

    def test_includes_category_names_and_descriptions(self):
        categories = [
            CategoryRule(id="1", name="Groceries", description="Food and drink"),
            CategoryRule(id="2", name="Transport", description="Travel and fuel"),
        ]
        prompt = _build_bedrock_prompt("Tesco", categories)
        assert "Groceries" in prompt
        assert "Transport" in prompt
        assert "Food and drink" in prompt
        assert "Tesco" in prompt
        assert "Merchant" in prompt

    def test_instructs_returns_only_category_name(self):
        categories = [CategoryRule(id="1", name="Groceries", description="Food")]
        prompt = _build_bedrock_prompt("Sainsbury", categories)
        assert "category name" in prompt.lower()


class TestLoadCategories:
    """Tests for load_categories — category cache management."""

    def test_loads_from_seed_when_no_db(self):
        cats = load_categories(db_categories=None)
        assert len(cats) > 0
        assert all(isinstance(c, CategoryRule) for c in cats)
        # Seed data contains lowercase merchant keywords
        assert any("tesco" in c.merchant_keywords for c in cats)

    def test_loads_from_db_categories(self):
        db_cats = [
            {
                "id": "abc-123",
                "name": "Custom",
                "description": "Custom category",
                "merchant_keywords": ["CustomShop"],
                "associated_tickers": ["CSTM"],
            },
        ]
        cats = load_categories(db_categories=db_cats)
        assert len(cats) == 1
        assert cats[0].name == "Custom"
        assert cats[0].merchant_keywords == ["CustomShop"]

    def test_cache_returns_same_instance(self):
        # Reset cache
        import src.categories.merchant_map as mm

        mm._category_cache = None

        first = load_categories()
        second = load_categories()
        assert first is second  # same cached object


class TestGetCategories:
    """Tests for get_categories."""

    def test_returns_list(self):
        import src.categories.merchant_map as mm

        mm._category_cache = None

        cats = get_categories()
        assert len(cats) > 0


class TestMatchByKeyword:
    """Tests for match_by_keyword — substring keyword matching."""

    def test_matches_by_keyword(self):
        import src.categories.merchant_map as mm

        mm._category_cache = None
        mm.load_categories(
            [
                {
                    "id": "1",
                    "name": "Groceries",
                    "description": "Food shops",
                    "merchant_keywords": ["Tesco", "Sainsbury", "Asda"],
                    "associated_tickers": ["TSCO", "SBRY"],
                },
            ]
        )

        result = match_by_keyword("Tesco Stores")
        assert result is not None
        assert result.name == "Groceries"

    def test_no_match_returns_none(self):
        import src.categories.merchant_map as mm

        mm._category_cache = None
        mm.load_categories(
            [
                {
                    "id": "1",
                    "name": "Groceries",
                    "description": "Food",
                    "merchant_keywords": ["Tesco"],
                    "associated_tickers": [],
                },
            ]
        )

        result = match_by_keyword("SomeRandomPlace")
        assert result is None

    def test_case_insensitive_match(self):
        import src.categories.merchant_map as mm

        mm._category_cache = None
        mm.load_categories(
            [
                {
                    "id": "1",
                    "name": "Groceries",
                    "description": "Food",
                    "merchant_keywords": ["tesco"],
                    "associated_tickers": [],
                },
            ]
        )

        result = match_by_keyword("TESCO STORES")
        assert result is not None
        assert result.name == "Groceries"

    def test_empty_merchant_returns_none(self):
        assert match_by_keyword("") is None
        assert match_by_keyword("   ") is None


class TestResolveCategory:
    """Tests for resolve_category — combined keyword + LLM resolution."""

    @pytest.mark.asyncio
    async def test_keyword_match_returns_directly(self):
        """Stage 1 keyword match should return without calling Bedrock."""
        import src.categories.merchant_map as mm

        mm._category_cache = None
        mm.load_categories(
            [
                {
                    "id": "1",
                    "name": "Groceries",
                    "description": "Food",
                    "merchant_keywords": ["Tesco"],
                    "associated_tickers": [],
                },
            ]
        )

        with patch.object(mm, "classify_with_bedrock") as mock_bedrock:
            result = await resolve_category("Tesco")
            assert result is not None
            assert result.name == "Groceries"
            mock_bedrock.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_merchant_returns_none(self):
        result = await resolve_category("")
        assert result is None

    @pytest.mark.asyncio
    async def test_falls_back_to_bedrock_on_no_keyword_match(self):
        import src.categories.merchant_map as mm

        mm._category_cache = None
        mm.load_categories(
            [
                {
                    "id": "1",
                    "name": "Groceries",
                    "description": "Food shops",
                    "merchant_keywords": ["Tesco"],
                    "associated_tickers": [],
                },
            ]
        )

        with patch.object(
            mm,
            "classify_with_bedrock",
            return_value=CategoryRule(
                id="1",
                name="Groceries",
                description="Food shops",
                merchant_keywords=["Tesco"],
                associated_tickers=[],
            ),
        ):
            result = await resolve_category("Unknown Shop")
            assert result is not None
            assert result.name == "Groceries"
