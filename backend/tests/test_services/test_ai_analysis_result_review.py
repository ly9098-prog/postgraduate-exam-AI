"""Contracts for post-provider analysis review and terminal branch selection."""

from __future__ import annotations

import logging

import pytest

from app.services.ai.analysis_result_review import (
    resolve_analysis_outcome,
    review_analysis_result,
)
from app.services.ai.analysis_validation import AnalysisUsage
from app.services.ai.provider_invocation import ProviderInvocationResult


def invocation(runtime=None):
    return ProviderInvocationResult({"content": "raw", "model": "model"}, runtime)


def dependencies(**overrides):
    values = dict(
        image_data_urls=[],
        wrong_question_id=7,
        chat=None,
        expected_answer_check=["B"],
        answer_grounding={"answer": "B"},
        parse_content=lambda raw: {"parsed": raw},
        validate_content=lambda _parsed: True,
        extract_evidence=lambda _raw: "evidence",
        build_usage=lambda **kwargs: AnalysisUsage(
            "evidence", False, 0, kwargs["result"].get("tokens_used", 0), 20
        ),
        validate_answer_check=lambda raw, expected: (True, "passed", expected),
        diagnosis_contradicts_grounding=lambda _diagnosis, _grounding: (False, None),
        evidence_is_valid=lambda value: bool(value),
        should_retry_visual_ack=lambda **_kwargs: False,
        retry_visual_ack=None,
    )
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_review_combines_parse_usage_grounding_and_ack_failure():
    review = await review_analysis_result(invocation(), **dependencies())

    assert review.parsed == {"parsed": "raw"}
    assert review.parsed_valid is True
    assert review.usage.visual_evidence == "evidence"
    assert review.usage.total_duration_ms == 20
    assert review.grounding.valid is True
    assert review.grounding.answer_grounding == {"answer": "B"}
    assert review.ack_failure is None

    review = await review_analysis_result(
        invocation(),
        **dependencies(
            image_data_urls=["data:image/png;base64,x"],
            extract_evidence=lambda _raw: "",
            build_usage=lambda **kwargs: AnalysisUsage("", False, 0, 3, 20),
        ),
    )
    assert review.ack_failure is not None
    assert review.ack_failure.error_code == "vision_ack_missing"
    assert review.ack_failure.retryable is True


@pytest.mark.asyncio
async def test_outcome_selection_preserves_parse_and_grounding_order(caplog):
    logger = logging.getLogger("test-result-review")
    caplog.set_level(logging.INFO, logger="test-result-review")
    review = await review_analysis_result(
        invocation(), **dependencies(validate_content=lambda _parsed: False)
    )
    wrong_question = type("W", (), {"id": 7})()

    response = await resolve_analysis_outcome(
        None,
        review,
        wrong_question=wrong_question,
        user_id=2,
        context={},
        result=review.usage,
        image_data_urls=[],
        input_signature="input",
        model_signature="model",
        expected_answer_check=["B"],
        effective_force=True,
        runtime=object(),
        visual_evidence_is_valid=bool,
        max_tokens=800,
        logger=logger,
        visual_ack_failure=lambda **kwargs: pytest.fail("ack must not precede parse"),
        grounding_repair=lambda *_args, **_kwargs: pytest.fail(
            "invalid parse must not repair"
        ),
        valid_outcome=lambda *_args, **_kwargs: pytest.fail(
            "invalid parse must not succeed"
        ),
    )

    assert response["model"] == "parse_failed"
    assert response["force_regenerated"] is False
    assert response["cache_preserved"] is False
    assert caplog.records[0].getMessage() == (
        "ai.error_analysis.empty wq_id=7 force=True model=parse_failed"
    )


@pytest.mark.asyncio
async def test_valid_review_dispatches_to_valid_outcome_with_contract_fields():
    review = await review_analysis_result(invocation(), **dependencies())
    wrong_question = type("W", (), {"id": 7})()
    calls = []

    async def valid_outcome(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    response = await resolve_analysis_outcome(
        None,
        review,
        wrong_question=wrong_question,
        user_id=2,
        context={},
        result={"model": "model"},
        image_data_urls=["data:image/png;base64,x"],
        input_signature="input",
        model_signature="model",
        expected_answer_check=["B"],
        effective_force=False,
        runtime="runtime",
        visual_evidence_is_valid=bool,
        max_tokens=800,
        logger=logging.getLogger("test-result-review"),
        visual_ack_failure=lambda **_kwargs: pytest.fail("must not ack"),
        grounding_repair=lambda *_args, **_kwargs: pytest.fail("must not repair"),
        valid_outcome=valid_outcome,
    )

    assert response == {"ok": True}
    assert calls[0][1] == {
        "wrong_question": wrong_question,
        "user_id": 2,
        "context": {},
        "result": {"model": "model"},
        "parsed": review.parsed,
        "grounding": review.grounding,
        "usage": review.usage,
        "input_signature": "input",
        "model_signature": "model",
        "expected_answer_check": ["B"],
        "effective_force": False,
        "visual_evidence_is_valid": bool,
        "max_tokens": 800,
        "runtime": "runtime",
        "logger": calls[0][1]["logger"],
    }
