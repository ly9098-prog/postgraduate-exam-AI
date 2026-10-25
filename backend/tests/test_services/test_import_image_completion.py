"""Compatibility contract for image-import completion projection."""

from __future__ import annotations

import app.services.import_image_completion as completion


def request(result):
    return completion.ImageCompletionRequest(
        pipeline_id="pipeline-1",
        result=result,
        cleaned_text="cleaned text",
        raw_ocr_text="raw text",
        ocr_diagnostics={"cleaned_line_count": 2},
        runtime_diagnostics={"execution_backend": "local"},
        classify_result=lambda value, text: "classified-failure"
        if value.get("classify")
        else None,
    )


def test_completed_projection_preserves_batch_and_ocr_diagnostics():
    result = {
        "status": "completed",
        "batch_id": "batch-1",
        "stats": {"to_review": 7},
        "diagnostics": {"split": {"failure_reason": None}},
    }

    projected, status = completion.finalize_image_pipeline_result(request(result))

    assert status == "completed"
    assert projected["pipeline_id"] == "pipeline-1"
    assert projected["status"] == "completed"
    assert projected["raw_text_preview"] == "cleaned text"
    assert projected["question_count"] == 7
    assert projected["stats"]["ocr"] == {"cleaned_line_count": 2}
    assert projected["diagnostics"] == {
        "split": {"failure_reason": None},
        "ocr_runtime": {"execution_backend": "local"},
        "ocr_raw_text": "raw text",
        "ocr_cleaned_text": "cleaned text",
        "failure_reason": None,
    }
    assert projected["finished_at"]


def test_missing_review_batch_downgrades_and_appends_error():
    result = {"status": "completed", "stats": {"to_review": 0}, "errors": []}

    projected, status = completion.finalize_image_pipeline_result(request(result))

    assert status == "failed"
    assert "question_count" not in projected
    assert projected["diagnostics"]["failure_reason"] == "no_review_batch_created"
    assert projected["errors"] == ["OCR 文本未生成待审核批次"]


def test_classifier_result_is_kept_for_pipeline_failure():
    result = {
        "status": "failed",
        "batch_id": "",
        "errors": [],
        "classify": True,
    }

    projected, status = completion.finalize_image_pipeline_result(request(result))

    assert status == "failed"
    assert projected["diagnostics"]["failure_reason"] == "classified-failure"
    assert projected["errors"] == []
