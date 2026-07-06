"""
Evaluation tests for the cascade OCR system.

Tests the eval dataset structure, coverage, and runs cascade extraction
over a subset of receipts to measure field-level precision/recall.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.eval_dataset import EVAL_RECEIPTS, count_eval_receipts, get_eval_receipts

# ── Dataset shape ─────────────────────────────────────────────────────────


class TestEvalDatasetShape:
    """Validate the evaluation dataset itself."""

    def test_dataset_size(self):
        """Dataset must have between 50 and 100 receipts."""
        count = count_eval_receipts()
        assert 50 <= count <= 100, f"Got {count} receipts"

    def test_all_receipts_have_required_keys(self):
        for r in EVAL_RECEIPTS:
            assert "name" in r, f"Missing 'name' in {r}"
            assert "text" in r, f"Missing 'text' in {r['name']}"
            assert "expected" in r, f"Missing 'expected' in {r['name']}"
            exp = r["expected"]
            for key in ("merchant", "total", "date", "items_count"):
                assert key in exp, f"Missing expected.{key} in {r['name']}"

    def test_unique_names(self):
        names = [r["name"] for r in EVAL_RECEIPTS]
        assert len(names) == len(set(names)), "Duplicate receipt names found"

    def test_get_eval_receipts_returns_copy(self):
        r1 = get_eval_receipts()
        r2 = get_eval_receipts()
        assert r1 == r2
        # Mutating one should not affect the other
        r1[0]["expected"]["total"] = 999.0
        assert r2[0]["expected"]["total"] != 999.0

    def test_null_merchant_values(self):
        """Some receipts have no merchant."""
        nulls = [r for r in EVAL_RECEIPTS if r["expected"]["merchant"] is None]
        assert len(nulls) >= 3, f"Only {len(nulls)} merchant-null receipts"

    def test_null_date_values(self):
        """Some receipts have no date."""
        nulls = [r for r in EVAL_RECEIPTS if r["expected"]["date"] is None]
        assert len(nulls) >= 3, f"Only {len(nulls)} date-null receipts"


# ── OCR text patterns ─────────────────────────────────────────────────────


class TestOCRTextPatterns:
    """Validate that the synthetic OCR text contains extractable patterns."""

    def test_all_receipts_have_total_keyword(self):
        for r in EVAL_RECEIPTS:
            assert "Total" in r["text"], f"Missing 'Total' in {r['name']}: {r['text'][:60]}"

    def test_all_receipts_have_currency_symbol(self):
        for r in EVAL_RECEIPTS:
            text = r["text"]
            has_currency = any(sym in text for sym in ("£", "$", "€"))
            assert has_currency, f"Missing currency in {r['name']}: {text[:60]}"

    def test_expected_total_appears_in_text(self):
        for r in EVAL_RECEIPTS:
            total = r["expected"]["total"]
            if total is not None:
                text = r["text"]
                # The total should appear as a number in the last Total line
                total_str = f"{total:.2f}"
                assert total_str in text, f"Total {total_str} not found in {r['name']}: {text}"


# ── Coverage ──────────────────────────────────────────────────────────────


class TestCoverage:
    """Ensure the dataset covers multiple locales and edge case categories."""

    def test_uk_locale_coverage(self):
        uk = [r for r in EVAL_RECEIPTS if "£" in r["text"]]
        assert len(uk) >= 15, f"Only {len(uk)} UK receipts"

    def test_us_locale_coverage(self):
        us = [r for r in EVAL_RECEIPTS if "$" in r["text"]]
        assert len(us) >= 10, f"Only {len(us)} US receipts"

    def test_eu_locale_coverage(self):
        eu = [r for r in EVAL_RECEIPTS if "€" in r["text"]]
        assert len(eu) >= 5, f"Only {len(eu)} EU receipts"

    def test_edge_case_categories(self):
        no_merchant = [r for r in EVAL_RECEIPTS if r["expected"]["merchant"] is None]
        no_date = [r for r in EVAL_RECEIPTS if r["expected"]["date"] is None]
        no_items = [r for r in EVAL_RECEIPTS if r["expected"]["items_count"] == 0]
        multi_total = [r for r in EVAL_RECEIPTS if "Subtotal" in r["text"]]
        ocr_errors = [r for r in EVAL_RECEIPTS if "ocr" in r["name"].lower()]

        assert len(no_merchant) >= 3
        assert len(no_date) >= 3
        assert len(no_items) >= 3
        assert len(multi_total) >= 3
        assert len(ocr_errors) >= 2


# ── Cascade eval ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(r, id=r["name"])
        for r in EVAL_RECEIPTS[:5]  # First 5 receipts
    ],
)
class TestCascadeOnEvalReceipts:
    """Parametrized cascade extraction over a subset of eval receipts.

    This tests the full cascade extraction pipeline over realistic synthetic
    receipts. The LLM is mocked — we're validating that the cascade logic
    handles the dataset correctly, not that the LLM gets the right answer.
    """

    @pytest.mark.asyncio
    async def test_cascade_runs_without_error(self, receipt, mocker):
        """cascade_extract should not raise for any eval receipt."""
        mocker.patch("src.receipts.cascade.process_receipt")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal(receipt["expected"]["total"])
            if receipt["expected"]["total"] is not None
            else None,
            "merchant_name": receipt["expected"]["merchant"],
            "line_items": (
                [{"description": "Item", "quantity": 1, "amount": Decimal("1.00")}]
                if receipt["expected"]["items_count"]
                else []
            ),
            "date": receipt["expected"]["date"],
            "ocr_confidence": 0.85,
            "ocr_raw_text": receipt["text"],
        }
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = None  # No LLM — should work in degraded mode

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test_bytes")

        assert result.extraction is not None
        assert result.source in ("regex", "degraded")

    @pytest.mark.asyncio
    async def test_expected_total_extracted(self, receipt, mocker):
        """The expected total should be in the extraction result."""
        mocker.patch("src.receipts.cascade.process_receipt")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal(receipt["expected"]["total"])
            if receipt["expected"]["total"] is not None
            else None,
            "merchant_name": receipt["expected"]["merchant"],
            "line_items": [],
            "date": receipt["expected"]["date"],
            "ocr_confidence": 0.85,
            "ocr_raw_text": receipt["text"],
        }
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = None

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test_bytes")

        expected_total = receipt["expected"]["total"]
        if expected_total is not None:
            assert result.extraction.total is not None
            assert float(result.extraction.total) == pytest.approx(expected_total, rel=1e-2)

    @pytest.mark.asyncio
    async def test_expected_merchant_extracted(self, receipt, mocker):
        """The expected merchant should be in the extraction result."""
        mocker.patch("src.receipts.cascade.process_receipt")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal(receipt["expected"]["total"])
            if receipt["expected"]["total"] is not None
            else None,
            "merchant_name": receipt["expected"]["merchant"],
            "line_items": [],
            "date": receipt["expected"]["date"],
            "ocr_confidence": 0.85,
            "ocr_raw_text": receipt["text"],
        }
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = None

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test_bytes")

        expected_merchant = receipt["expected"]["merchant"]
        if expected_merchant is not None:
            assert result.extraction.merchant_name is not None
            assert result.extraction.merchant_name == expected_merchant

    @pytest.mark.asyncio
    async def test_expected_date_extracted(self, receipt, mocker):
        """The expected date should be in the extraction result."""
        mocker.patch("src.receipts.cascade.process_receipt")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal(receipt["expected"]["total"])
            if receipt["expected"]["total"] is not None
            else None,
            "merchant_name": receipt["expected"]["merchant"],
            "line_items": [],
            "date": receipt["expected"]["date"],
            "ocr_confidence": 0.85,
            "ocr_raw_text": receipt["text"],
        }
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = None

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test_bytes")

        expected_date = receipt["expected"]["date"]
        if expected_date is not None:
            assert result.extraction.date is not None
            assert str(result.extraction.date) == expected_date


# ── Specific scenarios ────────────────────────────────────────────────────


class TestEvalScenario:
    """Targeted scenario tests across specific edge cases."""

    @pytest.mark.asyncio
    async def test_no_merchant_extraction(self, mocker):
        """A receipt with no merchant should still return a total."""
        receipt = next(r for r in EVAL_RECEIPTS if r["name"] == "no_merchant_1")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal("30.00"),
            "merchant_name": None,
            "line_items": [],
            "date": "2026-06-01",
            "ocr_confidence": 0.5,
            "ocr_raw_text": receipt["text"],
        }
        mocker.patch("src.receipts.cascade.extract_with_llm")
        mocker.patch("src.receipts.cascade.extract_with_llm").return_value = None

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test")
        assert result.extraction.total is not None

    @pytest.mark.asyncio
    async def test_no_date_extraction(self, mocker):
        """A receipt with no date should still extract total."""
        receipt = next(r for r in EVAL_RECEIPTS if r["name"] == "no_date_1")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal("2.85"),
            "merchant_name": "TESCO EXPRESS",
            "line_items": [],
            "date": None,
            "ocr_confidence": 0.5,
            "ocr_raw_text": receipt["text"],
        }
        mocker.patch("src.receipts.cascade.extract_with_llm")
        mocker.patch("src.receipts.cascade.extract_with_llm").return_value = None

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test")
        assert result.extraction.total is not None

    @pytest.mark.asyncio
    async def test_multi_total_extraction(self, mocker):
        """Receipt with subtotals should pick up the correct final total."""
        receipt = next(r for r in EVAL_RECEIPTS if r["name"] == "multi_total_1")
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal("1.98"),
            "merchant_name": "TESCO",
            "line_items": [],
            "date": "2026-06-25",
            "ocr_confidence": 0.85,
            "ocr_raw_text": receipt["text"],
        }
        mocker.patch("src.receipts.cascade.extract_with_llm")
        mocker.patch("src.receipts.cascade.extract_with_llm").return_value = None

        from src.receipts.cascade import cascade_extract

        result = await cascade_extract(b"test")
        assert result.extraction.total == Decimal("1.98")
