"""Compatibility baseline for AI analysis cache signatures and projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION
from app.services.ai_service import (
    _analysis_input_signature,
    _analysis_model_signature,
    build_cached_error_analysis_response,
)


@dataclass
class Question:
    id: int
    content: dict
    options: dict | None
    answer: str
    question_type: str
    image_url: object = None
    current_version_id: int | None = None
    sync_version: int | None = None
    updated_at: datetime | None = None
    question_version_id: int | None = None


@dataclass
class WrongQuestion:
    question_id: int
    question_version_id: int | None
    wrong_answer: str
    error_type: str | None = None
    review_count: int = 0
    ai_analysis: dict | None = None


@dataclass
class Runtime:
    model_config_id: int
    provider: str
    model_name: str
    base_url: str


def question(**overrides):
    values = dict(
        id=7,
        content={"stem": "题干"},
        options={"A": "选项"},
        answer="A",
        question_type="single_choice",
    )
    values.setdefault("image_url", None)
    values.setdefault("current_version_id", None)
    values.setdefault("sync_version", None)
    values.setdefault("updated_at", None)
    values.setdefault("question_version_id", None)
    values.update(overrides)
    return Question(**values)


def wrong_question(**overrides):
    values = dict(
        question_id=7,
        question_version_id=3,
        wrong_answer="B",
        error_type="concept",
        review_count=2,
    )
    values.update(overrides)
    return WrongQuestion(**values)


def runtime(**overrides):
    values = dict(
        model_config_id=11,
        provider="openai-compatible",
        model_name="analysis",
        base_url="https://example.test/v1",
    )
    values.update(overrides)
    return Runtime(**values)


def fresh_analysis(**meta_overrides):
    meta = {
        "version": AI_ANALYSIS_PROMPT_VERSION,
        "grounding_guard": "passed",
        "generated_at": datetime.now(UTC).isoformat(),
        "visual_input_count": 1,
        "visual_evidence": "图中给出栈",
        "input_signature": "input",
        "model_signature": "model",
    }
    meta.update(meta_overrides)
    return {
        "mistake_diagnosis": "诊断",
        "knowledge_patch": "补漏",
        "review_task": "任务",
        "_meta": meta,
    }


def assert_changed_signature(wq, q, base, knowledge_points=None, visual_sources=None):
    assert (
        _analysis_input_signature(
            wq,
            q,
            knowledge_points or ["链表"],
            visual_sources=visual_sources,
        )
        != base
    )


def test_input_signature_covers_material_ai_inputs():
    base = _analysis_input_signature(
        wrong_question(), question(), ["链表"], visual_sources=["image.png"]
    )
    assert base

    changed_wqs = [
        wrong_question(wrong_answer="C"),
        wrong_question(error_type="calculation"),
        wrong_question(review_count=3),
        wrong_question(question_version_id=4),
    ]
    for changed in changed_wqs:
        assert_changed_signature(
            changed, question(), base, visual_sources=["image.png"]
        )

    changed_questions = [
        question(id=8),
        question(content={"stem": "新题干"}),
        question(options={"A": "新选项"}),
        question(answer="B"),
        question(question_type="multiple_choice"),
        question(current_version_id=9),
        question(question_version_id=10),
        question(sync_version=2),
        question(updated_at=datetime.now(UTC)),
        question(content={"segments": [{"type": "image", "url": "nested.png"}]}),
        question(options={"A": {"image_url": "option.png"}}),
    ]
    for changed in changed_questions:
        assert_changed_signature(wrong_question(), changed, base)

    assert_changed_signature(
        wrong_question(), question(), base, knowledge_points=["队列"]
    )
    assert_changed_signature(
        wrong_question(), question(), base, visual_sources=["other.png"]
    )


def test_input_signature_is_deterministic_and_uses_collected_visuals_by_default():
    q = question(image_url="image.png")
    explicit = _analysis_input_signature(
        wrong_question(), q, ["链表"], visual_sources=["image.png"]
    )
    default = _analysis_input_signature(wrong_question(), q, ["链表"])

    assert explicit == default
    assert _analysis_input_signature(wrong_question(), q, ["链表"]) == default


def test_model_signature_is_stable_and_covers_runtime_fields():
    base = _analysis_model_signature(runtime())
    assert base
    assert _analysis_model_signature(runtime()) == base
    assert _analysis_model_signature(None) is None

    for changed in [
        runtime(model_config_id=12),
        runtime(provider="other"),
        runtime(model_name="other"),
        runtime(base_url="https://other.test/v1"),
    ]:
        assert _analysis_model_signature(changed) != base


def test_cached_response_projection_and_stale_misses():
    wq = wrong_question(ai_analysis=fresh_analysis())
    cached = build_cached_error_analysis_response(
        wq,
        requires_visual=True,
        expected_input_signature="input",
        expected_model_signature="model",
    )

    assert cached == {
        "content": {
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "补漏",
            "review_task": "任务",
        },
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache",
        "duration_ms": 0,
        "visual_input_count": 1,
        "visual_evidence": "图中给出栈",
        "generated_at": wq.ai_analysis["_meta"]["generated_at"],
    }

    stale = wrong_question(
        ai_analysis=fresh_analysis(input_signature="old", model_signature="old")
    )
    assert (
        build_cached_error_analysis_response(
            stale,
            requires_visual=True,
            expected_input_signature="input",
            expected_model_signature="model",
        )
        is None
    )
    assert build_cached_error_analysis_response(wrong_question()) is None


def test_text_cache_projection_and_metadata_defaults():
    wq = wrong_question(
        ai_analysis={
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "补漏",
            "review_task": "任务",
            "_meta": {
                "version": AI_ANALYSIS_PROMPT_VERSION,
                "grounding_guard": "passed",
                "generated_at": datetime.now(UTC).isoformat(),
                "visual_input_count": 0,
                "visual_evidence": "",
            },
        }
    )

    cached = build_cached_error_analysis_response(wq, requires_visual=False)

    assert cached is not None
    assert cached["visual_input_count"] == 0
    assert cached["visual_evidence"] is None
    assert cached["generated_at"] == wq.ai_analysis["_meta"]["generated_at"]


@pytest.mark.parametrize(
    ("meta_overrides", "reason"),
    [
        ({"version": "old"}, "prompt_version"),
        ({"grounding_guard": "failed"}, "grounding_guard"),
        ({"visual_input_count": 0}, "visual_input"),
        ({"visual_evidence": "无法读取"}, "visual_evidence"),
        ({"input_signature": "old"}, "input_signature"),
        ({"model_signature": "old"}, "model_signature"),
    ],
)
def test_each_freshness_rejection_is_a_cache_miss(meta_overrides, reason):
    wq = wrong_question(ai_analysis=fresh_analysis(**meta_overrides))

    assert (
        build_cached_error_analysis_response(
            wq,
            requires_visual=True,
            expected_input_signature="input",
            expected_model_signature="model",
        )
        is None
    )
