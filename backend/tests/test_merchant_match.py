"""
Tests for receipts/merchant_match.py — fuzzy merchant name matching.

Uses RapidFuzz to match extracted merchant names against known merchants.
"""

from __future__ import annotations

from src.receipts.merchant_match import KNOWN_MERCHANTS, fuzzy_match_merchant


class TestFuzzyMatchMerchant:
    """Tests for fuzzy_match_merchant — string similarity matching."""

    def test_exact_match_returns_high_score(self):
        match, score = fuzzy_match_merchant("Tesco", ["Tesco", "Sainsbury", "Asda"])
        assert match == "Tesco"
        assert score >= 90

    def test_case_insensitive_match(self):
        match, score = fuzzy_match_merchant("tesco", ["Tesco", "Sainsbury"])
        assert match == "Tesco"
        assert score >= 90

    def test_fuzzy_match_slight_typo(self):
        match, score = fuzzy_match_merchant("Tescoo", ["Tesco", "Waitrose"])
        assert match is not None
        assert score >= 75

    def test_no_match_below_threshold(self):
        match, score = fuzzy_match_merchant("XYZUnknownMerchant", ["Tesco", "Asda"])
        assert match is None
        assert score == 0.0

    def test_empty_merchant_returns_none(self):
        match, score = fuzzy_match_merchant("", ["Tesco"])
        assert match is None
        assert score == 0.0

    def test_whitespace_only_returns_none(self):
        match, score = fuzzy_match_merchant("   ", ["Tesco"])
        assert match is None
        assert score == 0.0

    def test_empty_known_list_returns_none(self):
        match, score = fuzzy_match_merchant("Tesco", [])
        assert match is None
        assert score == 0.0

    def test_token_order_normalised(self):
        """Token set ratio normalises word order."""
        match, score = fuzzy_match_merchant(
            "Stores Tesco Limited",
            ["Tesco Stores", "Sainsbury Local"],
        )
        assert match is not None
        assert score >= 80

    def test_uses_default_known_merchants(self):
        """When known_merchants is None, uses module-level KNOWN_MERCHANTS."""
        assert len(KNOWN_MERCHANTS) > 0
        match, score = fuzzy_match_merchant("Tesco")
        # Tesco should be in the seed merchants
        assert match is not None
        assert score >= 50
