"""
Tests for the LLM-backed receipt extractor.

Exercises caching, JSON parsing, retry logic, and prompt construction.
All network calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.receipts.llm_extractor import (
    _build_extraction_prompt,
    _call_bedrock_with_retry,
    extract_with_llm,
)

# ── _build_extraction_prompt ──────────────────────────────────────────────


class TestPromptConstruction:
    """Prompt building should always return a non-empty string."""

    def test_prompt_contains_ocr_text(self):
        prompt = _build_extraction_prompt("Tesco\nTotal £10.00")
        assert "Tesco" in prompt
        assert "Total" in prompt
        assert "£10.00" in prompt

    def test_prompt_includes_instructions(self):
        """The prompt should contain JSON-related and extraction keywords."""
        prompt = _build_extraction_prompt("Milk £2.00")
        assert "JSON" in prompt
        assert "merchant" in prompt.lower()


# ── _call_bedrock_with_retry ──────────────────────────────────────────────


class TestCallBedrockWithRetry:
    """Tests for the raw Bedrock invocation wrapper (mocked)."""

    @pytest.mark.asyncio
    async def test_calls_chat_bedrock(self, mocker):
        """Should call ChatBedrock.ainvoke with the prompt."""
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        instance = mock_llm.return_value
        # ainvoke returns an object with .content
        mock_response = mocker.MagicMock()
        mock_response.content = '{"merchant_name": "Tesco"}'
        instance.ainvoke = AsyncMock(return_value=mock_response)

        result = await _call_bedrock_with_retry("test prompt")

        assert result == '{"merchant_name": "Tesco"}'
        instance.ainvoke.assert_awaited_once_with("test prompt")

    @pytest.mark.asyncio
    async def test_returns_none_when_content_none(self, mocker):
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        instance = mock_llm.return_value
        mock_response = mocker.MagicMock()
        mock_response.content = None
        instance.ainvoke = AsyncMock(return_value=mock_response)

        result = await _call_bedrock_with_retry("test prompt")
        assert result is None


# ── extract_with_llm ──────────────────────────────────────────────────────


class TestExtractWithLLM:
    """Tests for the public ``extract_with_llm`` function with mocked cache + Bedrock."""

    @pytest.mark.asyncio
    async def test_successful_extraction(self, mocker):
        """Successful Bedrock response with valid JSON returns a result."""
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_response = mocker.MagicMock()
        mock_response.content = (
            '{"merchant_name": "Tesco", "total_amount": 47.99, "date": "2026-06-25"}'
        )
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)
        mocker.patch("src.receipts.llm_extractor.set_cached_llm")

        result = await extract_with_llm("Tesco\nMilk 1.65\nTotal £47.99")

        assert result is not None
        assert result.merchant_name == "Tesco"
        assert result.total_amount == 47.99
        assert result.date == "2026-06-25"

    @pytest.mark.asyncio
    async def test_cache_hit_skips_bedrock(self, mocker):
        """When the cache has a valid entry, no Bedrock call is made."""
        mocker.patch(
            "src.receipts.llm_extractor.get_cached_llm",
            return_value={
                "merchant_name": "Cached",
                "total_amount": 10.00,
                "date": "2026-01-01",
            },
        )
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")

        result = await extract_with_llm("Tesco")

        assert result is not None
        assert result.merchant_name == "Cached"
        assert not mock_llm.called

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self, mocker):
        """When Bedrock returns unparseable JSON, result is None."""
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_response = mocker.MagicMock()
        mock_response.content = "not even json at all"
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)

        result = await extract_with_llm("Some text")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self, mocker):
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_response = mocker.MagicMock()
        mock_response.content = ""
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)
        result = await extract_with_llm("text")
        assert result is None

    @pytest.mark.asyncio
    async def test_null_fields_are_ok(self, mocker):
        """Optional fields can be null without failing extraction."""
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_response = mocker.MagicMock()
        mock_response.content = (
            '{"merchant_name": null, "total_amount": 47.99, "date": "2026-06-25"}'
        )
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)
        result = await extract_with_llm("text")

        assert result is not None
        assert result.merchant_name is None
        assert result.total_amount == 47.99

    @pytest.mark.asyncio
    async def test_all_null_not_cached(self, mocker):
        """When all fields are null, the result should not be cached."""
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_response = mocker.MagicMock()
        mock_response.content = '{"merchant_name": null, "total_amount": null, "date": null}'
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)
        mock_save = mocker.patch("src.receipts.llm_extractor.set_cached_llm")

        result = await extract_with_llm("some text")

        assert result is not None
        assert not mock_save.called

    @pytest.mark.asyncio
    async def test_retry_exhaustion_returns_none(self, mocker):
        """When Bedrock keeps failing, extract_with_llm returns None."""
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(side_effect=Exception("Always fails"))

        result = await extract_with_llm("some text")

        assert result is None

    @pytest.mark.asyncio
    async def test_partial_extraction_with_confidence(self, mocker):
        """LLM result should carry confidence values when provided."""
        mocker.patch("src.receipts.llm_extractor.get_cached_llm", return_value=None)
        mock_response = mocker.MagicMock()
        mock_response.content = '{"merchant_name": "Tesco", "total_amount": null, "date": null}'
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)

        result = await extract_with_llm("text")

        assert result is not None
        assert result.merchant_name == "Tesco"
        assert result.total_amount is None
        assert result.date is None
        assert isinstance(result.confidence, dict)


# ── Cache double-call safety ──────────────────────────────────────────────


class TestCacheConcurrency:
    """Two concurrent calls with the same text — without a distributed lock
    both may fire a Bedrock call.  (ponytail: add asyncio.Lock if throughput
    becomes a concern.)"""

    @pytest.mark.asyncio
    async def test_concurrent_calls_both_miss_cache(self, mocker):
        mock_get = mocker.patch("src.receipts.llm_extractor.get_cached_llm")
        mock_get.return_value = None  # first time

        mock_response = mocker.MagicMock()
        mock_response.content = (
            '{"merchant_name": "Tesco", "total_amount": 10.00, "date": "2026-01-01"}'
        )
        mock_llm = mocker.patch("langchain_aws.ChatBedrock")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)
        mocker.patch("src.receipts.llm_extractor.set_cached_llm")

        from asyncio import gather

        results = await gather(
            extract_with_llm("same text"),
            extract_with_llm("same text"),
        )

        assert all(r is not None for r in results)
        # Without a distributed lock both calls miss the cache and fire Bedrock.
        # ponytail: per-account locking if duplicate calls hurt the bill.
        assert mock_llm.return_value.ainvoke.call_count == 2


# ── CascadeDecisionDB model ────────────────────────────────────────────────


class TestCascadeDecisionDB:
    """Tests for the database ORM model."""

    def test_minimal_construction(self):
        from datetime import datetime

        from src.receipts.models import CascadeDecisionDB

        decision = CascadeDecisionDB(
            id="test-id",
            receipt_id="1",
            raw_text_hash="abc123",
            regex_confidence=0.95,
            chosen_source="regex",
            processing_time_ms=150,
            created_at=datetime(2026, 6, 25),
        )
        assert decision.receipt_id == "1"
        assert decision.chosen_source == "regex"
        assert decision.regex_confidence == 0.95

    def test_full_construction(self):
        from datetime import datetime

        from src.receipts.models import CascadeDecisionDB

        decision = CascadeDecisionDB(
            id="test-id-2",
            receipt_id="2",
            raw_text_hash="def456",
            regex_confidence=0.3,
            llm_confidence=0.85,
            chosen_source="cascade",
            discrepancies=[
                {"field": "merchant", "regex": "Old Store", "llm": "New Store"},
            ],
            field_confidences={
                "merchant": {"value": "New Store", "confidence": 0.9, "source": "llm"},
                "total": {"value": 47.99, "confidence": 0.95, "source": "regex"},
            },
            processing_time_ms=250,
            created_at=datetime(2026, 6, 25),
        )
        assert decision.discrepancies is not None
        assert decision.field_confidences is not None
        assert decision.llm_confidence == 0.85
