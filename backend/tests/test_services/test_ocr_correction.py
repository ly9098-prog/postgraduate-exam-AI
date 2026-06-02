"""Tests for AI OCR Correction Layer."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ocr_correction import (
    _detect_noise,
    _should_correct,
    correct_ocr_blocks,
    _token_usage,
    _reset_counters_if_needed,
)


# ---------------------------------------------------------------------------
# Noise detection tests
# ---------------------------------------------------------------------------


class TestDetectNoise:
    def test_clean_text_low_noise(self):
        block = {
            "normalized_text": (
                "1. 下列关于数据结构的说法正确的是\n"
                "A. 数据结构是数据元素的集合\n"
                "B. 数据结构是数据元素之间关系的集合\n"
                "C. 数据结构包含数据元素和元素之间的关系\n"
                "D. 以上说法都不对"
            ),
        }
        score = _detect_noise(block)
        assert score < 0.3

    def test_garbled_chars_high_noise(self):
        block = {
            "normalized_text": "1. 下列□关于数据□结构的说法□正确□的是□□\n□A□数据结构",
        }
        score = _detect_noise(block)
        assert score >= 0.3

    def test_short_lines_high_noise(self):
        block = {
            "normalized_text": "1.\n下列\n关于\n数据\n结构\n的\n说法\n正确\n的是",
        }
        score = _detect_noise(block)
        assert score >= 0.3

    def test_options_without_question_number(self):
        block = {
            "normalized_text": (
                "A. 数据结构是数据元素的集合\n"
                "B. 数据结构包含数据元素\n"
                "C. 数据结构包含关系\n"
                "D. 以上都对"
            ),
        }
        score = _detect_noise(block)
        assert score >= 0.2

    def test_fragmented_options(self):
        block = {
            "normalized_text": (
                "1. 下列关于数据结构的说法正确的是\n"
                "A. 数据结构是数据元素的集合"
            ),
        }
        score = _detect_noise(block)
        assert score >= 0.2

    def test_empty_block_zero_noise(self):
        block = {"normalized_text": ""}
        assert _detect_noise(block) == 0.0

    def test_none_text_zero_noise(self):
        block = {"normalized_text": None}
        assert _detect_noise(block) == 0.0


# ---------------------------------------------------------------------------
# Should-correct decision tests
# ---------------------------------------------------------------------------


class TestShouldCorrect:
    def test_mode_never(self):
        assert _should_correct(0.9, {"mode": "never"}) is False

    def test_mode_always(self):
        assert _should_correct(0.0, {"mode": "always"}) is True

    def test_auto_below_threshold(self):
        assert _should_correct(0.2, {"mode": "auto", "noise_threshold": 0.3}) is False

    def test_auto_above_threshold(self):
        assert _should_correct(0.5, {"mode": "auto", "noise_threshold": 0.3}) is True

    def test_auto_at_threshold(self):
        assert _should_correct(0.3, {"mode": "auto", "noise_threshold": 0.3}) is True
# ---------------------------------------------------------------------------
# AI correction integration tests (mocked)
# ---------------------------------------------------------------------------


class TestCorrectOcrBlocks:
    @pytest.mark.asyncio
    async def test_disabled_skips_all(self):
        blocks = [{"page": 1, "block_index": 0, "normalized_text": "some text"}]
        result = await correct_ocr_blocks(blocks, {"enabled": False})
        assert result["skipped_reason"] == "disabled"
        assert result["corrected_blocks"] == blocks
        assert result["stats"]["corrected_blocks"] == 0

    @pytest.mark.asyncio
    async def test_ai_unavailable_degrades(self):
        blocks = [{"page": 1, "block_index": 0, "normalized_text": "some text"}]
        with patch("app.ai.client.deepseek") as mock_client:
            mock_client.is_available.return_value = False
            result = await correct_ocr_blocks(blocks, {"enabled": True})
        assert result["skipped_reason"] == "ai_unavailable"

    @pytest.mark.asyncio
    async def test_low_noise_block_not_corrected(self):
        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": (
                "1. 下列关于数据结构的说法正确的是\n"
                "A. 数据结构是数据元素的集合\n"
                "B. 数据结构包含数据元素\n"
                "C. 数据结构包含关系\n"
                "D. 以上都对"
            ),
        }]
        with patch("app.ai.client.deepseek") as mock_client:
            mock_client.is_available.return_value = True
            result = await correct_ocr_blocks(blocks, {
                "enabled": True,
                "mode": "auto",
                "noise_threshold": 0.3,
            })
        assert result["stats"]["corrected_blocks"] == 0

    @pytest.mark.asyncio
    async def test_noisy_block_corrected(self):
        noisy_text = "1.\n下列\n关于\n数据\n结构\n的\n说法\n正确\n的是"
        corrected_text = "1. 下列关于数据结构的说法正确的是"
        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": noisy_text,
        }]

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.chat = AsyncMock(return_value={
            "content": corrected_text,
            "tokens_used": 50,
            "model": "deepseek-chat",
            "duration_ms": 100,
        })

        with patch("app.ai.client.deepseek", mock_deepseek):
            result = await correct_ocr_blocks(blocks, {
                "enabled": True,
                "mode": "auto",
                "noise_threshold": 0.3,
            })

        assert result["stats"]["corrected_blocks"] == 1
        assert result["corrected_blocks"][0]["normalized_text"] == corrected_text
        assert result["corrected_blocks"][0]["ocr_correction_applied"] is True

    @pytest.mark.asyncio
    async def test_token_limit_prevents_correction(self):
        noisy_text = "1.\n下列\n关于\n数据\n结构"
        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": noisy_text,
        }]

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True

        with patch("app.ai.client.deepseek", mock_deepseek):
            result = await correct_ocr_blocks(blocks, {
                "enabled": True,
                "mode": "always",
                "daily_token_limit": 0,
            })

        assert result["stats"]["corrected_blocks"] == 0

    @pytest.mark.asyncio
    async def test_ai_exception_degrades_gracefully(self):
        noisy_text = "1.\n下列\n关于\n数据\n结构\n的\n说法\n正确\n的是"
        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": noisy_text,
        }]

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.chat = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("app.ai.client.deepseek", mock_deepseek):
            result = await correct_ocr_blocks(blocks, {
                "enabled": True,
                "mode": "always",
            })

        assert result["stats"]["corrected_blocks"] == 0
        assert result["corrected_blocks"][0]["normalized_text"] == noisy_text

    @pytest.mark.asyncio
    async def test_empty_blocks_passthrough(self):
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": ""},
            {"page": 1, "block_index": 1, "normalized_text": None},
        ]
        with patch("app.ai.client.deepseek") as mock_client:
            mock_client.is_available.return_value = True
            result = await correct_ocr_blocks(blocks, {"enabled": True})
        assert len(result["corrected_blocks"]) == 2
        assert result["stats"]["corrected_blocks"] == 0

    @pytest.mark.asyncio
    async def test_ai_output_too_long_rejected(self):
        """AI output that's drastically longer than input is rejected."""
        noisy_text = "1. 题目"
        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": noisy_text,
        }]

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.chat = AsyncMock(return_value={
            "content": "1. 这是一个非常长的文本" * 50,
            "tokens_used": 200,
            "model": "deepseek-chat",
            "duration_ms": 100,
        })

        with patch("app.ai.client.deepseek", mock_deepseek):
            result = await correct_ocr_blocks(blocks, {
                "enabled": True,
                "mode": "always",
            })

        assert result["stats"]["corrected_blocks"] == 0
