"""Tests for math_detect_stage fix — no full-page upload, bbox validation.

Covers:
- bbox=None: no crop attempted, no URL generated, risk flag added
- bbox present: crop_from_page_ref is called (via mock)
- old Path(page_path).read_bytes() pattern is NOT used
- risk flag math_image_bbox_missing for missing bbox
- risk flag math_image_crop_failed for crop failure
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.pipeline_stages.math_detect_stage import (
    _is_valid_bbox,
    run_math_detect_stage,
)

# Sample question with complex formula
_MATH_QUESTION = {
    "stem": "求极限 $\\lim_{x \\to 0} \\frac{\\sin x}{x}$",
    "analysis": "",
    "page_start": 1,
    "risk_flags": [],
    "segments": [],
}


class TestIsValidBbox:
    def test_valid_bbox(self):
        assert _is_valid_bbox([100, 200, 500, 400]) is True

    def test_none_bbox(self):
        assert _is_valid_bbox(None) is False

    def test_empty_list(self):
        assert _is_valid_bbox([]) is False

    def test_wrong_length(self):
        assert _is_valid_bbox([1, 2, 3]) is False

    def test_reversed_coords(self):
        assert _is_valid_bbox([500, 100, 100, 400]) is False

    def test_negative_coords(self):
        assert _is_valid_bbox([-100, 0, 500, 400]) is False

    def test_string_values(self):
        assert _is_valid_bbox(["a", "b", "c", "d"]) is False

    def test_huge_coords(self):
        assert _is_valid_bbox([0, 0, 2_000_000, 2_000_000]) is False


class TestRunMathDetectNoFullPageUpload:
    """Core fix: Never upload full pages as formula screenshots."""

    @pytest.mark.asyncio
    async def test_bbox_none_does_not_upload(self):
        """When bbox is None, no upload should happen and risk flag should be set."""
        questions = [dict(_MATH_QUESTION)]
        # segments already have math_image with bbox=None as created by first pass
        questions[0]["segments"] = [{
            "type": "math_image",
            "url": None,
            "alt": "公式截图（暂未生成）",
            "source_page": 1,
            "bbox": None,
            "confidence": 0.5,
            "requires_review": True,
        }]
        questions[0]["parsed_content"] = {
            "text": "求极限",
            "render_mode": "segments",
            "segments": questions[0]["segments"],
        }

        result = await run_math_detect_stage(
            questions,
            pipeline_id="test_pipeline",
            page_image_refs={1: "/fake/page.png"},
        )

        updated = result["questions"][0]
        seg = updated["segments"][0]
        # URL should remain None (no full-page upload)
        assert seg["url"] is None, "Should not upload when bbox is None"
        assert seg["requires_review"] is True
        assert "math_image_bbox_missing" in (updated.get("risk_flags") or [])

    @pytest.mark.asyncio
    async def test_no_page_image_refs_no_crash(self):
        """When page_image_refs is None, no screenshot attempt should happen."""
        questions = [dict(_MATH_QUESTION)]
        result = await run_math_detect_stage(
            questions,
            pipeline_id="test_pipeline",
            page_image_refs=None,
        )
        assert len(result["questions"]) == 1

    @pytest.mark.asyncio
    async def test_valid_bbox_calls_crop_function(self):
        """When bbox is valid, crop_region should be called (not read_bytes)."""
        questions = [dict(_MATH_QUESTION)]
        questions[0]["segments"] = [{
            "type": "math_image",
            "url": None,
            "alt": "公式截图（暂未生成）",
            "source_page": 1,
            "bbox": [100, 200, 300, 400],  # valid bbox
            "confidence": 0.5,
            "requires_review": True,
        }]
        questions[0]["parsed_content"] = {
            "text": "求极限",
            "render_mode": "segments",
            "segments": questions[0]["segments"],
        }

        with (
            patch(
                "app.features.pipeline_stages.math_detect_stage.crop_region",
                new=AsyncMock(),
            ) as mock_crop,
            patch(
                "app.core.executor_registry.get_executor",
            ) as mock_get_executor,
        ):
            mock_executor = AsyncMock()
            # executor.run(fn, *args) must call fn(*args)
            async def _run(fn, *args, **kwargs):
                return await fn(*args, **kwargs)
            mock_executor.run = _run
            mock_get_executor.return_value = mock_executor
            mock_crop.side_effect = Exception("crop failed in test")
            result = await run_math_detect_stage(
                questions,
                pipeline_id="test_pipeline",
                page_image_refs={1: "/fake/page.png"},
            )

        mock_crop.assert_called_once()
        assert "math_image_crop_failed" in (result["questions"][0].get("risk_flags") or [])

    @pytest.mark.asyncio
    async def test_empty_questions_returns_empty(self):
        result = await run_math_detect_stage([], pipeline_id="test")
        assert result["questions"] == []
