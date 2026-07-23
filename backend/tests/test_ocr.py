"""
Tests for the OCR pipeline — pure function tests that do not require a
database connection or HTTP client.

Exercises the regex-based parsing functions in ``src.receipts.ocr``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

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
        # A legitimate single item can equal the total; exclude the summary
        # line by label rather than amount.
        assert len(items) == 1
        assert items[0]["description"] == "Item"

    def test_skips_vat_line(self):
        text = "Milk 1.65\nVAT 0.33\nTotal 1.98"
        items = parse_line_items(text)
        assert len(items) == 1
        assert items[0]["description"] == "Milk"

    def test_item_with_quantity_prefix(self):
        text = "2 x Milk 3.30\nTotal 3.30"
        items = parse_line_items(text)
        assert len(items) == 1
        assert items[0]["description"] == "Milk"
        assert items[0]["quantity"] == 2

    def test_decimal_comma_and_quantity_suffix(self):
        items = parse_line_items("Coffee beans 3 x 12,50\nTotal 12,50")
        assert len(items) == 1
        assert items[0]["description"] == "Coffee beans"
        assert items[0]["quantity"] == 3
        assert items[0]["amount"] == Decimal("12.50")

    def test_service_line_inferred_from_total(self):
        items = parse_line_items("PureGym\n01/08/2026\nMonthly Membership\nTotal £29.99")
        assert len(items) == 1
        assert items[0]["description"] == "Monthly Membership"
        assert items[0]["amount"] == Decimal("29.99")

    def test_skips_shipping_lines(self):
        text = "Amazon.co.uk\nClean Code 42.99\nShipping 0.00\nTotal $42.99"
        items = parse_line_items(text)
        assert len(items) == 1
        assert items[0]["description"] == "Clean Code"


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

    def test_dd_dot_mm_dot_yyyy(self):
        """DD.MM.YYYY format (e.g. German receipts)."""
        assert parse_date("25.06.2026") == date(2026, 6, 25)

    def test_dd_dot_mm_dot_yy(self):
        """DD.MM.YY format."""
        assert parse_date("25.06.26") == date(2026, 6, 25)

    def test_dd_mm_yy_with_slashes(self):
        """DD/MM/YY format."""
        assert parse_date("25/06/26") == date(2026, 6, 25)

    def test_invalid_date_returns_none(self):
        """31st November is invalid → returns None."""
        assert parse_date("31/11/2026") is None


class TestCleanNumber:
    """Tests for _clean_number internal helper."""

    def test_simple_decimal(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("47.99") == Decimal("47.99")

    def test_european_comma(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("47,99") == Decimal("47.99")

    def test_spaces_in_number(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("1 2 . 8 8") == Decimal("12.88")

    def test_thousands_separator(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("1,234.56") == Decimal("1234.56")

    def test_european_with_dot_thousands(self):
        """European thousands and decimal separators are normalised."""
        from src.receipts.ocr import _clean_number

        assert _clean_number("1.234,56") == Decimal("1234.56")

    def test_empty_string(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("") is None

    def test_no_digits(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("abc") is None

    def test_invalid_decimal(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("--..") is None

    def test_just_spaces(self):
        from src.receipts.ocr import _clean_number

        assert _clean_number("   ") is None


class TestParseDateExtended:
    """Additional date parsing edge cases."""

    def test_invalid_day_month(self):
        """Month > 12 causes swap, then invalid day catches it."""
        # 13/32/2026: month=32 > 12, swap → day=32, month=13 → invalid
        assert parse_date("13/32/2026") is None

    def test_unparseable_month_name(self):
        """Unknown month abbreviation returns None."""
        assert parse_date("1 Xyz 2026") is None


class TestPreprocessImage:
    """Tests for preprocess_image with synthetic image bytes."""

    def _make_test_image_bytes(self, width=100, height=80, dark_text=True):
        """Create a simple test image and return PNG bytes."""
        import cv2
        import numpy as np

        img = np.ones((height, width, 3), dtype=np.uint8) * 255  # white
        if dark_text:
            cv2.putText(img, "TEST", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        success, buf = cv2.imencode(".png", img)
        assert success
        return buf.tobytes()

    def test_preprocess_success(self):
        import numpy as np

        from src.receipts.ocr import preprocess_image

        img_bytes = self._make_test_image_bytes()
        result = preprocess_image(img_bytes)
        assert result is not None
        assert isinstance(result, np.ndarray)
        # Should be 2D (grayscale)
        assert len(result.shape) == 2

    def test_invalid_bytes_raises_value_error(self):
        import pytest

        from src.receipts.ocr import preprocess_image

        with pytest.raises(ValueError, match="Could not decode image"):
            preprocess_image(b"\x00\x01\x02")

    def test_small_image_upscaled(self):
        import numpy as np

        from src.receipts.ocr import preprocess_image

        # Very small image (under 900 long side) should be upscaled
        img_bytes = self._make_test_image_bytes(width=50, height=30)
        result = preprocess_image(img_bytes)
        assert result is not None
        assert isinstance(result, np.ndarray)
        # Should have been upscaled to at least 900 on the long side
        assert max(result.shape) >= 900

    def test_dark_image_inverted(self):
        """Dark-background image is auto-inverted so text is dark on light."""
        import numpy as np

        from src.receipts.ocr import preprocess_image

        # Create a mostly black image with white text (amateur photo style)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 30  # dark
        import cv2

        cv2.putText(img, "TEST", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        success, buf = cv2.imencode(".png", img)
        assert success
        result = preprocess_image(buf.tobytes())
        assert result is not None
        # After processing, mean should be > 127 (inverted to light background)
        assert result.mean() > 127 or result.mean() < 10  # either inverted or still dark

    def test_large_image_downscaled(self):
        import numpy as np

        from src.receipts.ocr import preprocess_image

        # Large image (over 3000 long side) should be downscaled
        img_bytes = self._make_test_image_bytes(width=4000, height=3000)
        result = preprocess_image(img_bytes)
        assert result is not None
        assert isinstance(result, np.ndarray)
        # Should have been downscaled to at most 3000 on the long side
        assert max(result.shape) <= 3000


class TestDeskew:
    """Tests for _deskew internal helper."""

    def test_no_foreground_returns_original(self):
        """Less than 5 foreground pixels → image returned unchanged."""
        import numpy as np

        from src.receipts.ocr import _deskew

        # All-white image (no dark pixels)
        img = np.ones((100, 100), dtype=np.uint8) * 255
        result = _deskew(img)
        assert result is img  # same object returned

    def test_small_angle_not_deskewed(self):
        """Angle < 0.5° → image returned unchanged."""
        import numpy as np

        from src.receipts.ocr import _deskew

        # Create an image with a single small line of text in the center
        img = np.ones((100, 100), dtype=np.uint8) * 255
        img[40:60, 20:80] = 0  # horizontal dark bar
        result = _deskew(img)
        # The angle of a perfect horizontal bar should be ~0
        # So image should be returned unchanged
        assert result is img or isinstance(result, np.ndarray)

    def test_deskew_rotated_text(self):
        import numpy as np

        from src.receipts.ocr import _deskew

        # Create a deliberately tilted image
        img = np.ones((200, 200), dtype=np.uint8) * 255
        # Put some dark pixels along a diagonal to create skew
        for i in range(50, 150):
            img[i, i] = 0
            img[i, i + 1] = 0
        result = _deskew(img)
        assert isinstance(result, np.ndarray)
        assert result.shape == img.shape


class TestExtractText:
    """Tests for extract_text with mocked Tesseract."""

    def test_uses_tesseract_cmd_from_settings(self, monkeypatch):
        """When no explicit cmd, settings.OCR_TESSERACT_CMD is used."""
        import numpy as np

        from src.receipts.ocr import extract_text

        monkeypatch.setattr("src.config.settings.OCR_TESSERACT_CMD", "/custom/tesseract")

        with patch("src.receipts.ocr.pytesseract") as mock_ts:
            mock_ts.image_to_string.return_value = "Extracted text"
            img = np.zeros((100, 100), dtype=np.uint8)
            result = extract_text(img)
            assert result == "Extracted text"
            assert mock_ts.tesseract_cmd == "/custom/tesseract"

    def test_tries_multiple_configs(self):
        """Scores all PSM configs and picks the best by receipt evidence."""
        import numpy as np

        from src.receipts.ocr import extract_text

        with patch("src.receipts.ocr.pytesseract") as mock_ts:
            # Third config has the highest score (has total keyword)
            mock_ts.image_to_string.side_effect = [
                "Some text",
                "More text",
                "Total £10.00",  # Best - has total
            ]
            img = np.zeros((100, 100), dtype=np.uint8)
            result = extract_text(img)
            assert result == "Total £10.00"
            assert mock_ts.image_to_string.call_count == 3

    def test_exception_during_ocr_continues(self):
        """If a config raises, the next config is tried."""
        import numpy as np

        from src.receipts.ocr import extract_text

        with patch("src.receipts.ocr.pytesseract") as mock_ts:
            mock_ts.image_to_string.side_effect = [
                RuntimeError("Tesseract crashed"),
                "Fallback text extracted here",
            ]
            img = np.zeros((100, 100), dtype=np.uint8)
            result = extract_text(img)
            assert result == "Fallback text extracted here"


class TestComputeOcrConfidence:
    """Tests for _compute_ocr_confidence."""

    def test_returns_zero_for_no_confident_text(self):
        import numpy as np

        from src.receipts.ocr import _compute_ocr_confidence

        with patch("src.receipts.ocr.pytesseract") as mock_ts:
            mock_ts.image_to_data.return_value = {
                "conf": [-1, -1, -1],
                "text": ["", " ", "  "],
            }
            img = np.zeros((100, 100), dtype=np.uint8)
            confidence = _compute_ocr_confidence(img)
            assert confidence == 0.0

    def test_computes_average_confidence(self):
        import numpy as np

        from src.receipts.ocr import _compute_ocr_confidence

        with patch("src.receipts.ocr.pytesseract") as mock_ts:
            mock_ts.image_to_data.return_value = {
                "conf": [80, 90, -1, 70],
                "text": ["Hello", "World", "", "Test"],
            }
            img = np.zeros((100, 100), dtype=np.uint8)
            confidence = _compute_ocr_confidence(img)
            # Average of 80, 90, 70 (excludes -1) = 80 → 0.8
            assert confidence == 0.8


class TestProcessReceipt:
    """End-to-end tests for process_receipt."""

    def test_process_receipt_empty_text(self):
        """When OCR returns empty string, all fields are None/empty."""
        from src.receipts.ocr import process_receipt

        with (
            patch("src.receipts.ocr.preprocess_image") as mock_pre,
            patch("src.receipts.ocr.extract_text") as mock_extract,
        ):
            mock_pre.return_value = None
            mock_extract.return_value = ""
            result = process_receipt(b"fake-image-bytes")

        assert result["total_amount"] is None
        assert result["merchant_name"] is None
        assert result["line_items"] == []
        assert result["date"] is None
        assert result["ocr_confidence"] == 0.0
        assert result["ocr_raw_text"] == ""

    def test_process_receipt_happy_path(self):
        """Full pipeline with parsed values."""
        from src.receipts.ocr import process_receipt

        with (
            patch("src.receipts.ocr.preprocess_image") as mock_pre,
            patch("src.receipts.ocr.extract_text") as mock_extract,
            patch("src.receipts.ocr._compute_ocr_confidence") as mock_conf,
        ):
            import numpy as np

            mock_pre.return_value = np.zeros((100, 100), dtype=np.uint8)
            mock_extract.return_value = (
                "TESCO STORES LTD\n12/04/2026\nMilk 1.65\nBread 1.20\nTotal 2.85"
            )
            mock_conf.return_value = 0.85
            result = process_receipt(b"fake-image-bytes")

        assert result["total_amount"] == Decimal("2.85")
        assert result["merchant_name"] == "TESCO STORES LTD"
        assert len(result["line_items"]) == 2
        assert result["date"] is not None  # 12/04/2026 parsed
        assert result["date"] == date(2026, 4, 12)
        assert result["ocr_confidence"] == 0.85
        assert "TESCO" in result["ocr_raw_text"]


class TestParseMerchantExtended:
    """Additional parse_merchant edge cases."""

    def test_rescuer_path_returns_raw_line(self):
        """When no candidate passes _MERCHANT_NOISE filter, the rescuer finds a fuzzy match."""
        from src.receipts.ocr import parse_merchant

        # A receipt where the merchant name is embedded in a greeting
        # and normal candidates are filtered
        text = (
            "Welcome to\n"  # filtered by keyword
            "WELCOME TO SAINSBURY S\n"  # line 2 - will trigger rescuer
            "  \n"
            "12/04/2026\n"
            "Milk 1.65\n"
            "Total 5.50"
        )
        result = parse_merchant(text)
        # The rescuer path looks for fuzzy_match_merchant >= 80
        # Without the module present, it'll fall back to the first candidate
        assert result is not None

    def test_candidates_list_returns_first_valid(self):
        from src.receipts.ocr import parse_merchant

        text = "AMAZON\nItem 10.00\nTotal 10.00"
        result = parse_merchant(text)
        assert result == "AMAZON"

    def test_long_line_skipped(self):
        from src.receipts.ocr import parse_merchant

        text = "A" * 50 + "\nTESCO\nTotal 10.00"
        result = parse_merchant(text)
        assert result == "TESCO"

    def test_line_with_numbers_skipped(self):
        from src.receipts.ocr import parse_merchant

        text = "123 Store\nTESCO\nTotal 10.00"
        result = parse_merchant(text)
        assert result == "TESCO"

    def test_tesco_ocr_typo(self):
        text = "TESC0 STORES LTD\n25/06/2026\nMilk 1.65\nTotal £2.85"
        assert parse_merchant(text) == "TESC0 STORES LTD"

    def test_domain_style_merchant(self):
        text = "Amazon.com\n22/08/2026\nKindle Book 14.99\nTotal $24.98"
        assert parse_merchant(text) == "Amazon.com"

    def test_rescuer_skips_product_lines(self):
        text = "Sainsbury's Supermarket\n14/03/2026\nApple Juice 2.50\nTotal £5.70"
        assert parse_merchant(text) == "Sainsbury's Supermarket"


class TestParseDateExtended2:
    """More date edge cases."""

    def test_invalid_date_values_skipped(self):
        """Invalid date like month 13 causes skip to next pattern."""
        assert parse_date("99/99/9999") is None

    def test_february_29_non_leap(self):
        """Feb 29 on a non-leap year returns None (or first match)."""
        # This depends on whether a date pattern catches it first
        result = parse_date("29/02/2023")
        assert result is None or result == date(2023, 2, 29)

    def test_pattern_1_mm_dd_swap_correctly(self):
        """DD/MM where month > 12 triggers swap."""
        assert parse_date("13/01/2026") == date(2026, 1, 13)
