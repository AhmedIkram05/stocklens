"""
Tests for spending categories — seed data, keyword matching, and API endpoints.

Endpoint tests use the per-test DB transaction from ``conftest``.
Unit tests for keyword matching do not require a database connection.
"""

from __future__ import annotations

import httpx
import pytest

from src.categories.merchant_map import (
    load_categories,
    match_by_keyword,
)
from src.categories.seed import CATEGORY_NAMES, SEED_CATEGORIES

# ── Seed data ────────────────────────────────────────────────────────────────


class TestSeedData:
    """Verify the seed data is well-formed."""

    def test_has_ten_categories(self):
        assert len(SEED_CATEGORIES) >= 10

    def test_all_categories_have_names(self):
        for cat in SEED_CATEGORIES:
            assert cat["name"], f"Category missing name: {cat}"

    def test_no_duplicate_keywords(self):
        all_keywords: list[str] = []
        for cat in SEED_CATEGORIES:
            all_keywords.extend(cat["merchant_keywords"])
        assert len(all_keywords) == len(set(all_keywords)), "Duplicate keywords found"

    def test_expected_categories_exist(self):
        expected = {"Groceries", "Dining Out", "Transportation", "Shopping"}
        assert expected.issubset(set(CATEGORY_NAMES))


# ── Keyword matching ─────────────────────────────────────────────────────────


class TestKeywordMatching:
    """Tests for the ``match_by_keyword`` function."""

    def setup_method(self):
        # Ensure categories are loaded from seed data
        load_categories()

    def test_tesco_matches_groceries(self):
        cat = match_by_keyword("TESCO STORES LTD")
        assert cat is not None
        assert cat.name == "Groceries"

    def test_mcdonald_matches_dining(self):
        cat = match_by_keyword("McDonald's")
        assert cat is not None
        assert cat.name == "Dining Out"

    def test_uber_matches_transportation(self):
        cat = match_by_keyword("Uber")
        assert cat is not None
        assert cat.name == "Transportation"

    def test_amazon_matches_shopping(self):
        cat = match_by_keyword("Amazon")
        assert cat is not None
        assert cat.name == "Shopping"

    def test_netflix_matches_entertainment(self):
        cat = match_by_keyword("Netflix")
        assert cat is not None
        assert cat.name == "Entertainment"

    def test_unknown_merchant(self):
        cat = match_by_keyword("SomeRandomShop123")
        assert cat is None

    def test_empty_merchant(self):
        cat = match_by_keyword("")
        assert cat is None

    def test_none_merchant(self):
        cat = match_by_keyword("   ")
        assert cat is None

    def test_case_insensitive(self):
        cat = match_by_keyword("TESCO")
        assert cat is not None
        assert cat.name == "Groceries"

    def test_punctuation_stripped(self):
        cat = match_by_keyword("TESCO!!!")
        assert cat is not None
        assert cat.name == "Groceries"

    def test_boots_matches_health(self):
        cat = match_by_keyword("Boots Pharmacy")
        assert cat is not None
        assert cat.name == "Health & Pharmacy"


# ── API endpoints ────────────────────────────────────────────────────────────


class TestCategoriesAPI:
    """Tests for GET /categories and GET /categories/{id}."""

    @pytest.mark.usefixtures("_seed_categories")
    async def test_list_categories(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.get("/categories", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 10
        names = {c["name"] for c in data["categories"]}
        assert "Groceries" in names
        assert "Dining Out" in names

    @pytest.mark.usefixtures("_seed_categories")
    async def test_get_category_success(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        # Get list first to find a category ID
        list_resp = await client.get("/categories", headers=auth_headers)
        cat_id = list_resp.json()["categories"][0]["id"]
        response = await client.get(f"/categories/{cat_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["id"] == cat_id

    async def test_get_category_not_found(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        response = await client.get(
            "/categories/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_list_categories_unauthenticated(self, client: httpx.AsyncClient):
        response = await client.get("/categories")
        assert response.status_code == 401
