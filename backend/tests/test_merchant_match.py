"""
Tests for fuzzy merchant name matching.

All tests are pure function tests with no database dependency.

Exercises ``src.receipts.merchant_match.fuzzy_match_merchant()``.
"""

from __future__ import annotations

from src.receipts.merchant_match import fuzzy_match_merchant

TEST_MERCHANTS = [
    "tesco",
    "sainsbury",
    "starbucks",
    "uber",
    "amazon",
    "mcdonald",
    "netflix",
    "ikea",
    "boots",
    "costco",
]


class TestFuzzyMatchMerchant:
    """Tests for ``fuzzy_match_merchant``."""

    def test_exact_match(self):
        """Exact match returns the merchant with high score."""
        match, score = fuzzy_match_merchant("tesco", TEST_MERCHANTS)
        assert match == "tesco"
        assert score > 80

    def test_case_insensitive(self):
        match, score = fuzzy_match_merchant("TESCO", TEST_MERCHANTS)
        assert match is not None
        assert score > 80

    def test_partial_match(self):
        """A merchant name containing a known keyword should match."""
        match, score = fuzzy_match_merchant("TESCO STORES LTD", TEST_MERCHANTS)
        assert match is not None
        assert score > 80

    def test_close_match(self):
        """Minor OCR typos should still match."""
        match, score = fuzzy_match_merchant("TESC0", TEST_MERCHANTS)
        assert match is not None
        assert score >= 80

    def test_no_match(self):
        """Unknown merchant returns None and 0.0."""
        match, score = fuzzy_match_merchant("XYZCORP LTD", TEST_MERCHANTS)
        assert match is None
        assert score == 0.0

    def test_empty_string(self):
        match, score = fuzzy_match_merchant("", TEST_MERCHANTS)
        assert match is None
        assert score == 0.0

    def test_whitespace_only(self):
        match, score = fuzzy_match_merchant("   ", TEST_MERCHANTS)
        assert match is None
        assert score == 0.0

    def test_word_order_insensitive(self):
        """Token sort ratio handles word reordering."""
        match, score = fuzzy_match_merchant("STORES TESCO", TEST_MERCHANTS)
        assert match == "tesco"
        assert score > 80

    def test_multiple_word_match(self):
        match, score = fuzzy_match_merchant("Starbucks Coffee Company", TEST_MERCHANTS)
        assert match is not None
        assert score > 80

    def test_default_merchants(self):
        """Without providing known_merchants, uses the module-level list."""
        match, score = fuzzy_match_merchant("Tesco Express")
        assert match is not None
        assert score > 80
