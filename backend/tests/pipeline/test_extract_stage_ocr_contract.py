"""Pin one-pass OCR fallback and exercise-region filtering before refactoring."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.extract_stage_support import ObservedMapping, make_extract_harness


@pytest.mark.parametrize(
    "options,detects",
    [
        ({}, True),
        ({"import_mode": "exam"}, False),
        ({"import_mode": "book"}, True),
        ({"page_start": 1}, False),
        ({"page_end": 4}, False),
        ({"page_start": 0, "page_end": None}, True),
    ],
)
def test_exercise_detection_only_runs_without_exam_or_truthy_user_range(
    monkeypatch, options, detects
):
    h = make_extract_harness(monkeypatch)
    result = h.pipeline._run_extract(file_content=b"pdf", options=options)
    expected = ["pdf", "ocr", "page_texts", "detect"] if detects else ["pdf", "ocr"]
    assert [call[0] for call in h.trace] == expected
    assert result["exercise_regions_missing"] is detects
    assert result["raw_blocks"] is h.ocr_blocks
    ocr = next(call for call in h.trace if call[0] == "ocr")
    assert ocr[2] == {
        "pipeline_id": "extract-contract",
        "page_start": options.get("page_start") or 1,
        "page_end": options.get("page_end"),
    }
    if detects:
        assert h.trace[2] == ("page_texts", True)
        assert h.trace[3][2] == {
            "config": {"max_empty_pages": 2, "min_confidence": 0.8}
        }


def test_exercise_feature_disabled_does_not_mark_regions_missing(monkeypatch):
    h = make_extract_harness(monkeypatch)
    monkeypatch.setattr(settings, "EXERCISE_DETECTION_ENABLED", False)
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert [call[0] for call in h.trace] == ["pdf", "ocr"]
    assert result["exercise_regions_missing"] is False


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_ocr_failure_keeps_original_blocks_and_defers_vl_to_correction(
    monkeypatch, error_type
):
    h = make_extract_harness(monkeypatch)
    failure = error_type("synthetic failure")
    h.ocr_error = failure
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert result["raw_blocks"] is h.pdf_blocks
    assert result["exercise_regions_missing"] is False
    assert h.warnings[0][1] is failure
    prefix = (
        "OCR fallback unavailable:"
        if error_type is RuntimeError
        else "OCR fallback failed,"
    )
    assert h.warnings[0][0].startswith(prefix)
    assert "downstream ocr_correction" in h.warnings[1][0]
    assert [call[0] for call in h.trace] == ["pdf", "ocr"]


def test_empty_ocr_result_retains_original_text_without_a_second_ocr_call(monkeypatch):
    h = make_extract_harness(monkeypatch)
    h.ocr_blocks = []
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert result["raw_blocks"] is h.pdf_blocks
    assert [call[0] for call in h.trace] == ["pdf", "ocr"]
    assert [row[0] for row in h.warnings] == [
        "OCR returned no blocks",
        "Local OCR returned no blocks; downstream ocr_correction stage "
        "will attempt PaddleOCR-VL via OCRFixRouter",
    ]


@pytest.mark.parametrize("ocr_enabled", [False, True])
def test_empty_original_and_empty_ocr_are_rejected(monkeypatch, ocr_enabled):
    h = make_extract_harness(monkeypatch)
    h.pdf_blocks = h.ocr_blocks = []
    monkeypatch.setattr(settings, "OCR_ENABLED", ocr_enabled)
    with pytest.raises(ValueError, match="PDF 中未提取到文本内容"):
        h.pipeline._run_extract(file_content=b"pdf")


@pytest.mark.parametrize("stage", ["ocr", "detect"])
def test_extraction_cancellation_propagates_without_fallback_warning(
    monkeypatch, stage
):
    h = make_extract_harness(monkeypatch)
    cancellation = asyncio.CancelledError("synthetic cancellation")
    setattr(h, "ocr_error" if stage == "ocr" else "detect_error", cancellation)
    with pytest.raises(asyncio.CancelledError) as raised:
        h.pipeline._run_extract(file_content=b"pdf")
    assert raised.value is cancellation
    assert h.warnings == []


def test_ocr_callee_precedes_pipeline_id_property_and_remains_original(monkeypatch):
    h = make_extract_harness(monkeypatch)
    original_type = type(h.pipeline)

    class Pipeline(original_type):
        @property
        def pipeline_id(self):
            monkeypatch.setattr(
                orchestrator,
                "_ocr_scanned_pdf",
                lambda *_args, **_kwargs: pytest.fail("OCR callee already loaded"),
            )
            return "live-pipeline"

    h.pipeline = object.__new__(Pipeline)
    result = h.pipeline._run_extract(
        file_content=b"pdf", options={"import_mode": "exam"}
    )
    assert result["raw_blocks"] is h.ocr_blocks
    assert h.trace[1][2]["pipeline_id"] == "live-pipeline"


def test_options_reads_are_not_snapshotted_or_deduplicated(monkeypatch):
    h = make_extract_harness(monkeypatch)
    events = []
    options = ObservedMapping({"import_mode": "exam"}, events)
    h.pipeline._run_extract(file_content=b"pdf", options=options)
    assert events == [
        "page_start",
        "page_end",
        "import_mode",
        "page_start",
        "page_end",
        "page_start",
        "page_end",
        "_original_raw_text",
    ]


def test_logger_replacement_after_ocr_is_observed_by_final_success_log(monkeypatch):
    h = make_extract_harness(monkeypatch)
    events = []
    original = orchestrator._ocr_scanned_pdf

    def ocr(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(
            orchestrator,
            "logger",
            SimpleNamespace(
                info=lambda *row: events.append(row),
                warning=lambda *_row: pytest.fail("no warning expected"),
            ),
        )
        return result

    monkeypatch.setattr(orchestrator, "_ocr_scanned_pdf", ocr)
    result = h.pipeline._run_extract(
        file_content=b"pdf", options={"import_mode": "exam"}
    )
    assert result["raw_blocks"] is h.ocr_blocks
    assert events == [("OCR succeeded: %d blocks", 1)]


def test_warning_failure_escapes_without_replacing_ocr_failure_context(monkeypatch):
    h = make_extract_harness(monkeypatch)
    h.ocr_error = RuntimeError("OCR failed")
    failure = ValueError("logger failed")

    def warning(*_args):
        raise failure

    monkeypatch.setattr(orchestrator.logger, "warning", warning)
    with pytest.raises(ValueError) as caught:
        h.pipeline._run_extract(file_content=b"pdf")
    assert caught.value is failure
    assert caught.value.__context__ is h.ocr_error
