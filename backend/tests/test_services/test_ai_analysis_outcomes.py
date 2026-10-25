"""Contracts for terminal AI-analysis outcome persistence and logging."""

from __future__ import annotations

import logging

import pytest

from app.services.ai.analysis_outcomes import (
    build_analysis_usage,
    detect_visual_ack_failure,
    grounding_repair_outcome,
    valid_analysis_outcome,
    visual_ack_failure_outcome,
)
from app.services.ai.analysis_validation import AnalysisUsage, GroundingValidation


def make_usage(**overrides) -> AnalysisUsage:
    values = {
        "visual_evidence": "图中给出栈",
        "visual_ack_retried": True,
        "visual_ack_retry_ms": 12,
        "total_tokens_used": 31,
        "total_duration_ms": 150,
    }
    values.update(overrides)
    return AnalysisUsage(**values)


def make_grounding(*, valid: bool, reason: str = "passed") -> GroundingValidation:
    validation = GroundingValidation(valid, reason, ["B"])
    validation.answer_grounding = {"answer": "B"}
    return validation


def test_usage_builder_extracts_visual_evidence_only_for_vision_requests():
    def extract(value):
        return f"evidence:{value}"

    vision = build_analysis_usage(
        raw_content="raw",
        result={"tokens_used": "12", "duration_ms": "34"},
        image_data_urls=["data:image/png;base64,x"],
        extract_evidence=extract,
    )
    text = build_analysis_usage(
        raw_content="raw",
        result={"tokens_used": 0, "duration_ms": 0},
        image_data_urls=[],
        extract_evidence=extract,
    )

    assert vision == AnalysisUsage("evidence:raw", False, 0, 12, 34)
    assert text == AnalysisUsage("", False, 0, 0, 0)


def test_visual_ack_failure_detection_and_log_contract(caplog):
    logger = logging.getLogger("test-analysis-outcome")
    caplog.set_level(logging.INFO, logger="test-analysis-outcome")

    assert (
        detect_visual_ack_failure(
            image_data_urls=[], visual_evidence="", evidence_is_valid=lambda _: False
        )
        is None
    )
    assert (
        detect_visual_ack_failure(
            image_data_urls=["data:image/png;base64,x"],
            visual_evidence="valid",
            evidence_is_valid=lambda _: True,
        )
        is None
    )

    missing = detect_visual_ack_failure(
        image_data_urls=["data:image/png;base64,x"],
        visual_evidence=" ",
        evidence_is_valid=lambda _: False,
    )
    invalid = detect_visual_ack_failure(
        image_data_urls=["data:image/png;base64,x"],
        visual_evidence="无法读取图中内容",
        evidence_is_valid=lambda _: False,
    )
    assert (missing.error_code, missing.retryable, missing.evidence_text) == (
        "vision_ack_missing",
        True,
        "",
    )
    assert (invalid.error_code, invalid.retryable) == ("vision_parse_failed", False)

    response = visual_ack_failure_outcome(
        wrong_question_id=7,
        result={"model": "analysis-model"},
        image_data_urls=["data:image/png;base64,x"],
        usage=make_usage(),
        visual_ack_retried=True,
        failure=invalid,
        logger=logger,
    )
    assert response["error_code"] == "vision_parse_failed"
    assert response["retryable"] is False
    assert response["tokens_used"] == 31
    assert response["duration_ms"] == 150
    assert caplog.records[0].getMessage() == (
        "ai.error_analysis.visual_ack_failed wq_id=7 model=analysis-model "
        "evidence='无法读取图中内容' retried=True error_code=vision_parse_failed "
        "retryable=False"
    )


@pytest.mark.asyncio
async def test_grounding_repair_preserves_payload_and_warning_contract(caplog):
    logger = logging.getLogger("test-analysis-outcome")
    caplog.set_level(logging.WARNING, logger="test-analysis-outcome")
    calls = []

    async def persist(*args, **kwargs):
        calls.append((args, kwargs))
        return {"mistake_diagnosis": "safe"}, "2026-10-26T00:00:00Z"

    wrong_question = type("WrongQuestion", (), {"id": 7})()
    response = await grounding_repair_outcome(
        None,
        wrong_question=wrong_question,
        user_id=11,
        context={"question": {}},
        result={"model": "analysis-model"},
        grounding=make_grounding(valid=False, reason="answer_mismatch"),
        usage=make_usage(),
        image_data_urls=["data:image/png;base64,x"],
        input_signature="input",
        model_signature="model",
        expected_answer_check=["B"],
        effective_force=True,
        runtime=type("Runtime", (), {})(),
        logger=logger,
        persist=persist,
    )

    assert response == {
        "content": {"mistake_diagnosis": "safe"},
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": 31,
        "model": "grounding_guard",
        "duration_ms": 150,
        "force_regenerated": True,
        "visual_input_count": 1,
        "visual_evidence": "图中给出栈",
        "input_mode": "vision",
        "generated_at": "2026-10-26T00:00:00Z",
        "grounding_repaired": True,
    }
    assert calls[0][1] == {
        "wrong_question": wrong_question,
        "user_id": 11,
        "context": {"question": {}},
        "result": {"model": "analysis-model"},
        "answer_grounding": {"answer": "B"},
        "visual_evidence": "图中给出栈",
        "visual_ack_retried": True,
        "visual_ack_retry_ms": 12,
        "image_count": 1,
        "input_signature": "input",
        "model_signature": "model",
        "expected_answer_check": ["B"],
        "grounding_guard_reason": "answer_mismatch",
        "actual_answer_check": ["B"],
        "tokens_used": 31,
        "duration_ms": 150,
        "effective_force": True,
        "runtime": calls[0][1]["runtime"],
    }
    assert caplog.records[0].getMessage() == (
        "ai.error_analysis.grounding_repaired wq_id=7 force=True "
        "model=analysis-model reason=answer_mismatch expected=['B'] actual=['B']"
    )


@pytest.mark.asyncio
async def test_valid_outcome_preserves_persistence_and_result_log_contract(caplog):
    logger = logging.getLogger("test-analysis-outcome")
    caplog.set_level(logging.INFO, logger="test-analysis-outcome")
    calls = []

    async def persist(*args, **kwargs):
        calls.append((args, kwargs))
        return "2026-10-26T00:01:00Z"

    wrong_question = type("WrongQuestion", (), {"id": 7})()
    parsed = {
        "mistake_diagnosis": "诊断",
        "knowledge_patch": "",
        "review_task": None,
        "_meta": {"generated_at": "2026-10-26T00:01:00Z"},
    }
    result = {
        "model": "analysis-model",
        "compatibility_profile": "profile",
    }
    response = await valid_analysis_outcome(
        None,
        wrong_question=wrong_question,
        user_id=11,
        context={"question": {}},
        result=result,
        parsed=parsed,
        grounding=make_grounding(valid=True),
        usage=make_usage(),
        image_data_urls=["data:image/png;base64,x"],
        input_signature="input",
        model_signature="model",
        expected_answer_check=["B"],
        effective_force=False,
        visual_evidence_is_valid=lambda value: value == "图中给出栈",
        max_tokens=800,
        runtime=type("Runtime", (), {})(),
        logger=logger,
        persist=persist,
    )

    assert response["generated_at"] == "2026-10-26T00:01:00Z"
    assert response["model"] == "analysis-model"
    assert response["tokens_used"] == 31
    assert calls[0][1]["wrong_question"] is wrong_question
    assert calls[0][1]["parsed"] is parsed
    assert calls[0][1]["answer_grounding"] == {"answer": "B"}
    assert calls[0][1]["tokens_used"] == 31
    assert caplog.records[0].getMessage() == (
        "ai.error_analysis.result wq_id=7 force=False model=analysis-model "
        "input_mode=vision visual_count=1 visual_evidence_valid=True "
        "parsed_valid=True compatibility=profile max_tokens=800 "
        "visual_ack_retried=True visual_ack_retry_ms=12 "
        "fields={'mistake_diagnosis': True, 'knowledge_patch': False, "
        "'review_task': False} duration_ms=150"
    )
