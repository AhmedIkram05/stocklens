"""
Tests for receipts/merchant_match.py — fuzzy merchant name matching.

Uses RapidFuzz to match extracted merchant names against known merchants.
"""

from __future__ import annotations

import pytest
from rapidfuzz import fuzz

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


class TestExtractOneParity:
    """The native ``process.extractOne`` scan must reproduce the previous Python
    loop exactly: same match, same score, same >=80 threshold, first-wins ties,
    and the original casing from the choices list."""

    @staticmethod
    def _reference(name: str, merchants: list[str]) -> tuple[str | None, float]:
        best_score, best_match = 0.0, None
        for known in merchants:
            score = fuzz.token_set_ratio(name.lower(), known.lower())
            if score > best_score:
                best_score, best_match = score, known
        return (best_match, best_score) if best_score >= 80 else (None, 0.0)

    @pytest.mark.parametrize(
        "name",
        [
            "Tesco",
            "tesco",
            "TESCO STORES",
            "Stores Tesco Limited",
            "Tescoo",
            "Sainsbury Local",
            "Waitrose & Partners",
            "Asda Stores Ltd",
            "XYZUnknownMerchant",
            "",
            "   ",
        ],
    )
    def test_matches_reference_over_default_merchants(self, name: str) -> None:
        assert fuzzy_match_merchant(name) == self._reference(name, KNOWN_MERCHANTS)

    @pytest.mark.parametrize("name", ["abc", "Tesco", "xabc", "zzzz"])
    def test_matches_reference_over_override_list(self, name: str) -> None:
        merchants = ["abcx", "Tesco", "xabc", "asda"]
        assert fuzzy_match_merchant(name, merchants) == self._reference(name, merchants)

    def test_returns_first_match_on_tie(self) -> None:
        # Both choices score identically; the previous strict-`>` loop kept the first.
        match, score = fuzzy_match_merchant("abc", ["abcx", "xabc"])
        assert match == "abcx"
        assert score == pytest.approx(fuzz.token_set_ratio("abc", "abcx"))

    def test_preserves_original_casing_from_choices(self) -> None:
        match, _ = fuzzy_match_merchant("tesco", ["Tesco"])
        assert match == "Tesco"

    def test_below_threshold_returns_none_and_zero(self) -> None:
        assert fuzzy_match_merchant("zzzzzzzz", ["abcdefgh"]) == (None, 0.0)

    def test_lowered_index_matches_default_merchants(self) -> None:
        from src.receipts.merchant_match import KNOWN_MERCHANTS_LOWER

        assert KNOWN_MERCHANTS_LOWER == [m.lower() for m in KNOWN_MERCHANTS]
