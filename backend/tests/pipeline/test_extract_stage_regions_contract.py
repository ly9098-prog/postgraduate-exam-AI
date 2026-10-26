"""Exercise-region projection retains accepted OCR and partial results on failure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.features import exercise_region_detector
from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.extract_stage_support import make_extract_harness


def test_regions_filter_inclusive_pages_preserving_block_order_and_identity(
    monkeypatch,
):
    h = make_extract_harness(monkeypatch)
    h.ocr_blocks = [{"page": page, "text": str(page)} for page in [5, 1, 3, 2, 6]]
    h.regions = [
        SimpleNamespace(
            start_page=2, end_page=3, confidence=0.9, matched_keyword="exercise"
        ),
        SimpleNamespace(
            start_page=5, end_page=5, confidence=0.8, matched_keyword="practice"
        ),
    ]
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert result["raw_blocks"] == [h.ocr_blocks[0], h.ocr_blocks[2], h.ocr_blocks[3]]
    assert result["raw_blocks"] is not h.ocr_blocks
    assert result["raw_blocks"][0] is h.ocr_blocks[0]
    assert result["exercise_regions"] == [
        {
            "start_page": 2,
            "end_page": 3,
            "confidence": 0.9,
            "matched_keyword": "exercise",
        },
        {
            "start_page": 5,
            "end_page": 5,
            "confidence": 0.8,
            "matched_keyword": "practice",
        },
    ]
    assert result["exercise_regions_missing"] is False
    assert sum(call[0] == "ocr" for call in h.trace) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_detection_failure_after_ocr_success_keeps_ocr_blocks(monkeypatch, error_type):
    h = make_extract_harness(monkeypatch)
    failure = error_type("detect failure")
    h.detect_error = failure
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert result["raw_blocks"] is h.ocr_blocks
    assert result["exercise_regions_missing"] is False
    assert len(h.warnings) == 1
    assert h.warnings[0][1] is failure
    assert sum(call[0] == "ocr" for call in h.trace) == 1


def test_detector_loaded_before_page_text_callback_rebinds_module_port(monkeypatch):
    h = make_extract_harness(monkeypatch)

    def page_texts(blocks):
        assert blocks is h.ocr_blocks
        monkeypatch.setattr(
            exercise_region_detector,
            "detect_exercise_regions",
            lambda *_args, **_kwargs: pytest.fail("local detector already imported"),
        )
        monkeypatch.setattr(settings, "EXERCISE_DETECTION_MAX_EMPTY_PAGES", 7)
        return {1: "changed text"}

    monkeypatch.setattr(orchestrator, "_extract_page_texts_from_blocks", page_texts)
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert result["exercise_regions_missing"] is True
    assert h.trace[-1] == (
        "detect",
        {1: "changed text"},
        {"config": {"max_empty_pages": 7, "min_confidence": 0.8}},
    )


@pytest.mark.parametrize("failure_point", ["projection", "page_range", "filtered_log"])
def test_region_failure_keeps_exact_partial_projection_without_ocr_retry(
    monkeypatch,
    failure_point,
):
    h = make_extract_harness(monkeypatch)
    failure = ValueError("region partial failure")

    class Region:
        start_page = 1
        confidence = 0.9

        @property
        def end_page(self):
            return "bad" if failure_point == "page_range" else 1

        @property
        def matched_keyword(self):
            if failure_point == "projection":
                raise failure
            return "exercise"

    h.ocr_blocks = [{"page": 1, "text": "kept"}, {"page": 2, "text": "removed"}]
    h.regions = [Region()]
    initial_info = orchestrator.logger.info

    def info(message, *args):
        if failure_point == "filtered_log" and message.startswith("Exercise region"):
            raise failure
        initial_info(message, *args)

    monkeypatch.setattr(orchestrator.logger, "info", info)
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert len(h.warnings) == 1
    assert sum(call[0] == "ocr" for call in h.trace) == 1
    assert result["exercise_regions_missing"] is False
    if failure_point == "projection":
        assert result["exercise_regions"] == []
        assert result["raw_blocks"] is h.ocr_blocks
    else:
        assert result["exercise_regions"][0]["matched_keyword"] == "exercise"
        if failure_point == "page_range":
            assert result["raw_blocks"] is h.ocr_blocks
        else:
            assert result["raw_blocks"] == [h.ocr_blocks[0]]
            assert result["raw_blocks"] is not h.ocr_blocks


def test_filtering_every_ocr_block_out_is_rejected_without_retry_or_vl_warning(
    monkeypatch,
):
    h = make_extract_harness(monkeypatch)
    h.regions = [
        SimpleNamespace(
            start_page=99,
            end_page=99,
            confidence=0.9,
            matched_keyword="exercise",
        )
    ]
    with pytest.raises(ValueError, match="PDF 中未提取到文本内容"):
        h.pipeline._run_extract(file_content=b"pdf")
    assert h.warnings == []
    assert sum(call[0] == "ocr" for call in h.trace) == 1
