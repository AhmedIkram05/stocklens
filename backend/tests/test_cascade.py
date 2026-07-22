"""
Tests for the cascade orchestrator — confidence scoring, discrepancy
detection, merge logic, and the full cascade flow.

All tests are pure function tests that mock the LLM and OCR layer.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from src.receipts.cascade import (
    _compute_overall_confidence,
    _detect_discrepancies,
    _merge_results,
    _score_heuristic_confidence,
    _should_escalate,
    cascade_extract,
)
from src.receipts.llm_extractor import LLMExtractionResult
from src.receipts.models import FieldConfidence

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_regex_result() -> dict:
    """A typical successful regex extraction result."""
    return {
        "total_amount": Decimal("47.99"),
        "merchant_name": "TESCO STORES LTD",
        "line_items": [
            {"description": "Milk", "quantity": 1, "amount": Decimal("1.65")},
            {"description": "Bread", "quantity": 1, "amount": Decimal("1.20")},
        ],
        "date": date(2026, 6, 25),
        "ocr_confidence": 0.87,
        "ocr_raw_text": "TESCO STORES LTD\n25/06/2026\nMilk 1.65\nBread 1.20\nTotal £47.99",
    }


@pytest.fixture
def known_merchants() -> list[str]:
    return ["tesco", "sainsbury", "waitrose"]


# ── _score_heuristic_confidence ───────────────────────────────────────────


class TestScoreHeuristicConfidence:
    """Tests for ``_score_heuristic_confidence``."""

    def test_all_fields_found(self, sample_regex_result, known_merchants):
        confs = _score_heuristic_confidence(sample_regex_result, "", known_merchants)
        assert "total" in confs
        assert "merchant" in confs
        assert "date" in confs
        assert "items" in confs
        assert confs["total"].confidence == 0.95
        assert confs["merchant"].confidence == 0.95  # boosted by fuzzy match
        assert confs["date"].confidence == 0.85
        assert confs["items"].confidence > 0.5

    def test_missing_total(self, sample_regex_result, known_merchants):
        result = dict(sample_regex_result, total_amount=None)
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["total"].confidence == 0.0
        assert confs["total"].value is None

    def test_missing_merchant(self, sample_regex_result, known_merchants):
        result = dict(sample_regex_result, merchant_name=None)
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["merchant"].confidence == 0.0
        assert confs["merchant"].value is None

    def test_missing_date(self, sample_regex_result, known_merchants):
        result = dict(sample_regex_result, date=None)
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["date"].confidence == 0.0
        assert confs["date"].value is None

    def test_empty_items(self, sample_regex_result, known_merchants):
        result = dict(sample_regex_result, line_items=[])
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["items"].confidence == 0.0

    def test_items_confidence_scaling(self, known_merchants):
        """Item confidence increases with count, capped at 0.90."""
        result = {
            "total_amount": Decimal("10.00"),
            "merchant_name": "Shop",
            "line_items": [
                {"description": f"Item {i}", "quantity": 1, "amount": Decimal("1.00")}
                for i in range(8)
            ],
            "date": date(2026, 1, 1),
            "ocr_confidence": 0.9,
            "ocr_raw_text": "text",
        }
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["items"].confidence <= 0.90

    def test_merchant_boost_with_fuzzy_match(self, known_merchants):
        """Merchant matching known merchants gets boosted to 0.95."""
        result = {
            "total_amount": Decimal("10.00"),
            "merchant_name": "TESCO STORES",
            "line_items": [],
            "date": date(2026, 1, 1),
            "ocr_confidence": 0.9,
            "ocr_raw_text": "text",
        }
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["merchant"].confidence == 0.95

    def test_merchant_no_boost_without_match(self, known_merchants):
        """Unknown merchant stays at base 0.90."""
        result = {
            "total_amount": Decimal("10.00"),
            "merchant_name": "RANDOM CORP",
            "line_items": [],
            "date": date(2026, 1, 1),
            "ocr_confidence": 0.9,
            "ocr_raw_text": "text",
        }
        confs = _score_heuristic_confidence(result, "", known_merchants)
        assert confs["merchant"].confidence == 0.90


# ── _compute_overall_confidence ───────────────────────────────────────────


class TestComputeOverallConfidence:
    """Tests for ``_compute_overall_confidence``."""

    def test_all_fields_high(self):
        confs = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.9, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
        }
        overall = _compute_overall_confidence(confs)
        assert overall > 0.8

    def test_one_field_missing(self):
        confs = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.9, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.0, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
        }
        overall = _compute_overall_confidence(confs)
        assert overall < 0.6

    def test_all_fields_zero(self):
        confs = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.0, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.0, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.0, source="regex"),
        }
        assert _compute_overall_confidence(confs) == 0.0

    def test_empty_confidences(self):
        assert _compute_overall_confidence({}) == 0.0


# ── _detect_discrepancies ─────────────────────────────────────────────────


class TestDetectDiscrepancies:
    """Tests for ``_detect_discrepancies``."""

    def test_no_discrepancies_when_values_match(self):
        heuristic = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.9, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="Tesco",
            total_amount=10.0,
            date="2026-01-01",
            confidence={"merchant_name": 0.9, "total_amount": 0.95, "date": 0.85},
        )
        discrepancies = _detect_discrepancies(heuristic, llm)
        assert len(discrepancies) == 0

    def test_discrepancy_detected(self):
        heuristic = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.9, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="Sainsbury",
            total_amount=10.0,
            date="2026-01-01",
            confidence={"merchant_name": 0.9, "total_amount": 0.95, "date": 0.85},
        )
        discrepancies = _detect_discrepancies(heuristic, llm)
        assert len(discrepancies) == 1
        assert discrepancies[0]["field"] == "merchant"
        assert discrepancies[0]["regex"] == "Tesco"
        assert discrepancies[0]["llm"] == "Sainsbury"

    def test_no_discrepancy_when_llm_confidence_low(self):
        """When LLM has low confidence, no discrepancy should be logged."""
        heuristic = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.9, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="RANDOM",  # Different, but...
            total_amount=99.99,  # Different, but...
            date="2026-06-15",
            confidence={"merchant_name": 0.2, "total_amount": 0.1, "date": 0.3},  # low conf
        )
        discrepancies = _detect_discrepancies(heuristic, llm)
        assert len(discrepancies) == 0

    def test_no_discrepancy_when_heuristic_confidence_low(self):
        """When regex has low confidence, no discrepancy should be logged."""
        heuristic = {
            "merchant": FieldConfidence(value=None, confidence=0.0, source="regex"),
            "total": FieldConfidence(value=None, confidence=0.0, source="regex"),
            "date": FieldConfidence(value=None, confidence=0.0, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="Tesco",
            total_amount=10.0,
            date="2026-01-01",
            confidence={"merchant_name": 0.9, "total_amount": 0.95, "date": 0.85},
        )
        discrepancies = _detect_discrepancies(heuristic, llm)
        assert len(discrepancies) == 0


# ── _merge_results ────────────────────────────────────────────────────────


class TestMergeResults:
    """Tests for ``_merge_results``."""

    def test_picks_regex_when_higher_confidence(self):
        heuristic = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.95, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
            "items": FieldConfidence(value=[], confidence=0.0, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="Tesco",
            total_amount=9.99,
            date="2026-01-01",
            confidence={"merchant_name": 0.8, "total_amount": 0.8, "date": 0.7},
        )
        merged = _merge_results(heuristic, llm, [])
        assert merged.field_confidences["merchant"].source == "regex"
        assert merged.field_confidences["total"].value == 10.0

    def test_picks_llm_when_higher_confidence(self):
        heuristic = {
            "merchant": FieldConfidence(value=None, confidence=0.0, source="regex"),
            "total": FieldConfidence(value=None, confidence=0.0, source="regex"),
            "date": FieldConfidence(value=None, confidence=0.0, source="regex"),
            "items": FieldConfidence(value=[], confidence=0.0, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="Tesco",
            total_amount=47.99,
            date="2026-06-25",
            confidence={
                "merchant_name": 0.9,
                "total_amount": 0.95,
                "date": 0.85,
                "line_items": 0.0,
            },
        )
        merged = _merge_results(heuristic, llm, [])
        assert merged.field_confidences["merchant"].source == "llm"
        assert merged.field_confidences["total"].value == 47.99

    def test_discrepancies_carried_through(self):
        heuristic = {
            "merchant": FieldConfidence(value="Tesco", confidence=0.9, source="regex"),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
            "items": FieldConfidence(value=[], confidence=0.0, source="regex"),
        }
        llm = LLMExtractionResult(
            merchant_name="Sainsbury",
            total_amount=10.0,
            date="2026-01-01",
            confidence={
                "merchant_name": 0.95,
                "total_amount": 0.8,
                "date": 0.7,
                "line_items": 0.0,
            },
        )
        discrepancies = [{"field": "merchant", "regex": "Tesco", "llm": "Sainsbury"}]
        merged = _merge_results(heuristic, llm, discrepancies)
        assert len(merged.discrepancies) == 1
        assert merged.discrepancies[0]["field"] == "merchant"


# ── _should_escalate ────────────────────────────────────────────────────


class TestShouldEscalate:
    """Tests for the LLM escalation decision (confidence gating)."""

    @staticmethod
    def _confs(merchant_conf: float, has_merchant: bool = True) -> dict:
        return {
            "merchant": FieldConfidence(
                value="Shop" if has_merchant else None,
                confidence=merchant_conf if has_merchant else 0.0,
                source="regex",
            ),
            "total": FieldConfidence(value=10.0, confidence=0.95, source="regex"),
            "date": FieldConfidence(value="2026-01-01", confidence=0.85, source="regex"),
        }

    def test_no_escalation_when_verified_and_clean(self):
        """Verified merchant + high overall + high OCR → regex only."""
        confs = self._confs(0.95)
        escalate, reasons = _should_escalate(0.92, confs, 0.9)
        assert escalate is False
        assert reasons == ""

    def test_escalate_on_unverified_merchant(self):
        """Merchant found but not fuzzy-matched → escalate for LLM confirm."""
        confs = self._confs(0.90)
        escalate, reasons = _should_escalate(0.90, confs, 0.9)
        assert escalate is True
        assert "unverified_merchant" in reasons

    def test_escalate_on_low_ocr_quality(self):
        """Poor OCR engine confidence → escalate even if fields look present."""
        confs = self._confs(0.95)
        escalate, reasons = _should_escalate(0.92, confs, 0.4)
        assert escalate is True
        assert "low_ocr_quality" in reasons

    def test_escalate_on_low_overall(self):
        """Missing/low core field → escalate."""
        confs = self._confs(0.95, has_merchant=False)
        escalate, reasons = _should_escalate(0.32, confs, 0.9)
        assert escalate is True
        assert "low_overall" in reasons


# ── cascade_extract (mocked) ─────────────────────────────────────────────


class TestCascadeExtract:
    """End-to-end cascade flow tests with mocked LLM."""

    @pytest.mark.asyncio
    async def test_regex_only_when_high_confidence(self, mocker):
        """When OCR confidence is high, cascade returns regex result immediately."""
        mock_process = mocker.patch("src.receipts.cascade.process_receipt")
        mock_process.return_value = {
            "total_amount": Decimal("47.99"),
            "merchant_name": "TESCO STORES LTD",
            "line_items": [{"description": "Milk", "quantity": 1, "amount": Decimal("1.65")}],
            "date": date(2026, 6, 25),
            "ocr_confidence": 0.95,
            "ocr_raw_text": "TESCO STORES LTD\n25/06/2026\nMilk 1.65\nTotal £47.99",
        }

        result = await cascade_extract(b"fake_image_bytes")

        assert result.source == "regex"
        assert result.overall_confidence >= 0.7
        assert result.extraction.merchant_name == "TESCO STORES LTD"
        assert result.extraction.total == Decimal("47.99")

    @pytest.mark.asyncio
    async def test_vision_success(self, mocker):
        """When vision LLM succeeds, cascade returns cascade source with vision data."""
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": None,
            "merchant_name": None,
            "line_items": [],
            "date": None,
            "ocr_confidence": 0.3,
            "ocr_raw_text": "Some garbled text\nTotal £47.99",
        }

        mock_vision = mocker.patch("src.receipts.cascade.extract_with_vision")
        mock_vision.return_value = LLMExtractionResult(
            merchant_name="Tesco",
            total_amount=47.99,
            date="2026-06-25",
            confidence={
                "merchant_name": 0.9,
                "total_amount": 0.95,
                "date": 0.85,
                "line_items": 0.0,
            },
        )

        result = await cascade_extract(b"fake_image_bytes")

        assert mock_vision.called
        assert result.source == "cascade"
        assert result.extraction.merchant_name == "Tesco"
        assert result.extraction.total == Decimal("47.99")

    @pytest.mark.asyncio
    async def test_vision_fallback_to_text_llm(self, mocker):
        """When vision fails, cascade falls back to text LLM."""
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal("47.99"),
            "merchant_name": None,
            "line_items": [],
            "date": None,
            "ocr_confidence": 0.3,
            "ocr_raw_text": "Some garbled text\nTotal £47.99",
        }

        mocker.patch("src.receipts.cascade.extract_with_vision", return_value=None)
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = LLMExtractionResult(
            merchant_name="Tesco",
            total_amount=47.99,
            date="2026-06-25",
            confidence={
                "merchant_name": 0.9,
                "total_amount": 0.95,
                "date": 0.85,
                "line_items": 0.0,
            },
        )

        result = await cascade_extract(b"fake_image_bytes")

        assert mock_llm.called
        assert result.source == "cascade"

    @pytest.mark.asyncio
    async def test_degraded_when_llm_fails(self, mocker):
        """When vision AND text LLM both fail, cascade returns degraded regex result."""
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": Decimal("47.99"),
            "merchant_name": None,
            "line_items": [],
            "date": None,
            "ocr_confidence": 0.3,
            "ocr_raw_text": "Some garbled text\nTotal £47.99",
        }

        mocker.patch("src.receipts.cascade.extract_with_vision", return_value=None)
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = None  # both failed

        result = await cascade_extract(b"fake_image_bytes")

        assert result.source == "degraded"
        assert result.extraction.total == Decimal("47.99")

    @pytest.mark.asyncio
    async def test_failed_when_no_text(self, mocker):
        """Empty OCR text returns source='failed'."""
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": None,
            "merchant_name": None,
            "line_items": [],
            "date": None,
            "ocr_confidence": 0.0,
            "ocr_raw_text": "",
        }

        result = await cascade_extract(b"fake_empty_image")

        assert result.source == "failed"
        assert result.overall_confidence == 0.0

    @pytest.mark.asyncio
    async def test_discrepancies_detected_in_cascade(self, mocker):
        """When regex and LLM disagree on high-confidence fields,
        discrepancies are captured."""
        mocker.patch("src.receipts.cascade.process_receipt").return_value = {
            "total_amount": None,  # no total → low heuristic conf → triggers LLM
            "merchant_name": "OLD NAME",
            "line_items": [],
            "date": None,  # no date → low heuristic conf
            "ocr_confidence": 0.5,
            "ocr_raw_text": "OLD NAME\n01/01/2026\nTotal £10.00",
        }

        mocker.patch("src.receipts.cascade.extract_with_vision", return_value=None)
        mock_llm = mocker.patch("src.receipts.cascade.extract_with_llm")
        mock_llm.return_value = LLMExtractionResult(
            merchant_name="NEW NAME",
            total_amount=10.00,
            date="2026-01-01",
            confidence={
                "merchant_name": 0.9,
                "total_amount": 0.8,
                "date": 0.8,
                "line_items": 0.0,
            },
        )

        result = await cascade_extract(b"fake_image_bytes")

        assert result.source == "cascade"
        assert mock_llm.called


# ── Decimal serialisation (Fix 6) ─────────────────────────────────────


class TestDecimalSerialization:
    """model_dump(mode='json') must produce JSON-serialisable output."""

    def test_model_dump_json_mode_serializable(self):
        from src.receipts.models import ExtractedItem

        item = ExtractedItem(name="Test", quantity=2, price=Decimal("42.50"))
        data = item.model_dump(mode="json")
        # Should not raise
        blob = json.dumps(data)
        assert '"price": 42.5' in blob

    def test_model_dump_json_mode_on_items_list_serializable(self):
        from src.receipts.models import ExtractedItem

        items = [
            ExtractedItem(name="Milk", quantity=1, price=Decimal("1.65")),
            ExtractedItem(name="Bread", quantity=2, price=Decimal("1.20")),
        ]
        blob = json.dumps([i.model_dump(mode="json") for i in items])
        assert "Milk" in blob
        assert "Bread" in blob
        assert "1.65" in blob

    def test_plain_model_dump_contains_decimals(self):
        """Without mode='json', Decimal values survive — proving why mode='json' is needed."""
        from src.receipts.models import ExtractedItem

        item = ExtractedItem(name="Test", quantity=1, price=Decimal("42.50"))
        data = item.model_dump()  # no mode="json"
        assert isinstance(data["price"], Decimal)
