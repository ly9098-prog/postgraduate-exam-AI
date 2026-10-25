"""Compatibility contract for analysis grounding and visual-ack reconciliation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.analysis_validation import (
    AnalysisUsage,
    VisualValidationRequest,
    reconcile_visual_evidence,
    validate_analysis_grounding,
)


def validation_request(**overrides):
    defaults = dict(
        result={"content": "raw", "model": "analysis-model"},
        image_data_urls=[],
        runtime=SimpleNamespace(model_name="analysis-model"),
        wrong_question_id=7,
        chat=None,
        extract_evidence=lambda value: value,
        validate_answer_check=lambda raw, expected: (True, "passed", expected),
        diagnosis_contradicts_grounding=lambda diagnosis, grounding: (False, None),
        evidence_is_valid=lambda value: bool(value),
        should_retry_visual_ack=lambda **kwargs: False,
        retry_visual_ack=None,
    )
    defaults.update(overrides)
    return VisualValidationRequest(**defaults)


def test_invalid_parsed_analysis_never_checks_grounding():
    validation = validate_analysis_grounding(
        parsed_valid=False,
        raw_content="raw",
        parsed_diagnosis="diagnosis",
        expected_answer_check=["A"],
        answer_grounding={"answer": "A"},
        validate_answer_check=lambda *_: (_ for _ in ()).throw(
            AssertionError("answer check must not run")
        ),
        diagnosis_contradicts_grounding=lambda *_: (_ for _ in ()).throw(
            AssertionError("contradiction check must not run")
        ),
    )

    assert validation.valid is False
    assert validation.guard_reason == "analysis_invalid"
    assert validation.actual_answer_check is None


def test_answer_check_failure_preserves_reason_and_actual_value():
    validation = validate_analysis_grounding(
        parsed_valid=True,
        raw_content="raw",
        parsed_diagnosis="diagnosis",
        expected_answer_check=["A"],
        answer_grounding={"answer": "A"},
        validate_answer_check=lambda raw, expected: (
            False,
            "answer_mismatch",
            ["B"],
        ),
        diagnosis_contradicts_grounding=lambda *_: (_ for _ in ()).throw(
            AssertionError("contradiction check must not run")
        ),
    )

    assert validation.valid is False
    assert validation.guard_reason == "answer_mismatch"
    assert validation.actual_answer_check == ["B"]


def test_diagnosis_contradiction_uses_model_reason_with_fallback():
    for returned in ("synthetic contradiction", None):

        def diagnosis_check(*_):
            return True, returned

        validation = validate_analysis_grounding(
            parsed_valid=True,
            raw_content="raw",
            parsed_diagnosis="diagnosis",
            expected_answer_check=["A"],
            answer_grounding={"answer": "A"},
            validate_answer_check=lambda raw, expected: (True, "passed", expected),
            diagnosis_contradicts_grounding=diagnosis_check,
        )
        assert validation.valid is False
        assert validation.guard_reason == (returned or "diagnosis_contradiction")


@pytest.mark.asyncio
async def test_visual_ack_retry_accumulates_usage_in_place():
    usage = AnalysisUsage(
        visual_evidence="",
        visual_ack_retried=False,
        visual_ack_retry_ms=0,
        total_tokens_used=10,
        total_duration_ms=100,
    )

    async def retry_visual_ack(*args, **kwargs):
        return SimpleNamespace(
            retried=True,
            retry_ms=25,
            tokens_used_delta=3,
            evidence="图中给出栈",
        )

    validation = await reconcile_visual_evidence(
        validation_request(
            image_data_urls=["data:image/png;base64,x"],
            should_retry_visual_ack=lambda **kwargs: True,
            retry_visual_ack=retry_visual_ack,
        ),
        {"mistake_diagnosis": "诊断"},
        parsed_valid=True,
        expected_answer_check=["A"],
        answer_grounding={"answer": "A"},
        usage=usage,
    )

    assert validation.valid is True
    assert usage.visual_ack_retried is True
    assert usage.visual_ack_retry_ms == 25
    assert usage.total_duration_ms == 125
    assert usage.total_tokens_used == 13
    assert usage.visual_evidence == "图中给出栈"


@pytest.mark.asyncio
async def test_valid_initial_evidence_skips_retry_probe():
    usage = AnalysisUsage(
        visual_evidence="图中给出栈",
        visual_ack_retried=False,
        visual_ack_retry_ms=0,
        total_tokens_used=10,
        total_duration_ms=100,
    )

    async def unexpected_retry(*args, **kwargs):
        raise AssertionError("retry probe must not run")

    await reconcile_visual_evidence(
        validation_request(
            image_data_urls=["data:image/png;base64,x"],
            retry_visual_ack=unexpected_retry,
        ),
        {"mistake_diagnosis": "诊断"},
        parsed_valid=True,
        expected_answer_check=["A"],
        answer_grounding={"answer": "A"},
        usage=usage,
    )

    assert usage.visual_ack_retried is False
    assert usage.total_duration_ms == 100
    assert usage.total_tokens_used == 10
