"""
Tests for the OCR pipeline — pure function tests that do not require a
database connection or HTTP client.

Exercises the regex-based parsing functions in ``src.receipts.ocr``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.receipts.ocr import (
    parse_date,
    parse_line_items,
    parse_merchant,
    parse_total,
)


# ── parse_total ──────────────────────────────────────────────────────────────


class TestParseTotal:
    """Tests for the ``parse_total`` function."""

    def test_total_pound(self):
        assert parse_total("Total £47.99") == Decimal("47.99")

    def test_total_dollar(self):
        assert parse_total("Total $123.45") == Decimal("123.45")

    def test_total_euro(self):
        assert parse_total("Total €50.00") == Decimal("50.00")

    def test_grand_total(self):
        assert parse_total("Grand Total: $123.45") == Decimal("123.45")

    def test_amount_due(self):
        assert parse_total("Amount Due: £47.99") == Decimal("47.99")

    def test_total_without_currency(self):
        assert parse_total("Total 47.99") == Decimal("47.99")

    def test_no_total(self):
        assert parse_total("No numbers here") is None

    def test_total_with_comma(self):
        assert parse_total("Total £1,234.56") == Decimal("1234.56")

    def test_empty_string(self):
        assert parse_total("") is None

    def test_only_currency_symbol(self):
        """A lone currency symbol should not match."""
        text = "TESCO STORES LTD\nMilk 1.65\n£"
        # The £ alone doesn't match any pattern, and "1.65" on a line without
        # a currency prefix also doesn't match our TOTAL_PATTERNS.
        assert parse_total(text) is None


# ── parse_merchant ───────────────────────────────────────────────────────────


class TestParseMerchant:
    """Tests for the ``parse_merchant`` function."""

    def test_basic_merchant(self):
        text = "TESCO STORES LTD\nMilk 1.65\nTotal £47.99"
        assert parse_merchant(text) == "TESCO STORES LTD"

    def test_skips_receipt_header(self):
        text = "RECEIPT\nTESCO STORES LTD\nMilk 1.65\nTotal £47.99"
        assert parse_merchant(text) == "TESCO STORES LTD"

    def test_skips_invoice(self):
        text = "INVOICE #123\nTESCO STORES LTD\nTotal £47.99"
        assert parse_merchant(text) == "TESCO STORES LTD"

    def test_skips_date_line(self):
        text = "25/06/2026\nTESCO STORES LTD\nMilk 1.65\nTotal 47.99"
        assert parse_merchant(text) == "TESCO STORES LTD"

    def test_skips_thank_you(self):
        text = "Thank you for shopping\nTESCO STORES LTD\nMilk 1.65\nTotal 47.99"
        assert parse_merchant(text) == "TESCO STORES LTD"

    def test_no_merchant(self):
        text = "Milk 1.65\nBread 2.00\nTotal 3.65"
        # All lines have digits → no merchant → None
        result = parse_merchant(text)
        assert result is None

    def test_merchant_with_ampersand(self):
        text = "Marks & Spencer\nFood Hall\nTotal £25.00"
        result = parse_merchant(text)
        assert result is not None
        assert "&" in result

    def test_short_line_skipped(self):
        """Lines shorter than 3 characters are skipped."""
        text = "AB\nTESCO\nTotal 10.00"
        result = parse_merchant(text)
        assert result is not None
        assert result != "AB"


# ── parse_line_items ─────────────────────────────────────────────────────────


class TestParseLineItems:
    """Tests for the ``parse_line_items`` function."""

    def test_basic_items(self):
        text = "TESCO STORES LTD\nMilk 1.65\nBread 1.20\nTotal 2.85"
        items = parse_line_items(text)
        assert len(items) == 2
        assert items[0]["description"] == "Milk"
        assert float(items[0]["amount"]) == 1.65
        assert items[1]["description"] == "Bread"
        assert float(items[1]["amount"]) == 1.20

    def test_empty_text(self):
        assert parse_line_items("") == []

    def test_skips_total_line(self):
        text = "Item 5.00\nTotal 5.00"
        items = parse_line_items(text)
        # "Total 5.00" should be excluded (>= total_amount)
        assert len(items) == 0  # item is same as total, filtered out

    def test_skips_vat_line(self):
        text = "Milk 1.65\nVAT 0.33\nTotal 1.98"
        items = parse_line_items(text)
        assert len(items) == 1
        assert items[0]["description"] == "Milk"

    def test_item_with_quantity_prefix(self):
        text = "2 x Milk 3.30\nTotal 3.30"
        items = parse_line_items(text)
        # Item price == total amount, so it's filtered out (no items returned)
        assert len(items) == 0


# ── parse_date ───────────────────────────────────────────────────────────────


class TestParseDate:
    """Tests for the ``parse_date`` function."""

    def test_uk_format_ddmmyyyy(self):
        assert parse_date("Date: 25/06/2026") == date(2026, 6, 25)

    def test_iso_format(self):
        assert parse_date("2026-06-25") == date(2026, 6, 25)

    def test_dd_mm_yyyy_with_dashes(self):
        assert parse_date("25-06-2026") == date(2026, 6, 25)

    def test_mm_dd_yyyy_swapped(self):
        """06/25/2026 should be interpreted as DD/MM = 25/06 (month > 12 triggers swap)."""
        assert parse_date("Date: 06/25/2026") == date(2026, 6, 25)

    def test_date_with_month_name(self):
        assert parse_date("25 Jun 2026") == date(2026, 6, 25)

    def test_month_name_first(self):
        assert parse_date("Jun 25, 2026") == date(2026, 6, 25)

    def test_no_date(self):
        assert parse_date("No date here") is None

    def test_empty_string(self):
        assert parse_date("") is None
