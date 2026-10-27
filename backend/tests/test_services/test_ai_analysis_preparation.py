"""Contracts for initial AI analysis loading and cache decisions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.analysis_preparation import (
    AnalysisPreparationRequest,
    prepare_analysis,
)


def statement_filters(statement):
    return {
        clause.left.key: clause.right.value for clause in statement.whereclause.clauses
    }


def harness(**overrides):
    wrong = SimpleNamespace(
        id=7,
        question_id=3,
        user_id=8,
        wrong_answer="B",
        ai_analysis={"_meta": {"model": "analysis"}},
    )
    question = SimpleNamespace(
        id=3,
        question_type="single_choice",
        content={"stem": "stem"},
        options={"A": "A"},
        answer="A",
    )
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: wrong),
            SimpleNamespace(scalar_one_or_none=lambda: question),
        ]
    )
    fields = {
        "db": db,
        "user_id": 8,
        "wrong_question_id": 7,
        "force_regenerate": False,
        "logger": SimpleNamespace(info=MagicMock()),
        "load_runtime": AsyncMock(return_value="runtime"),
        "build_grounding": lambda **kwargs: {"grounding": kwargs},
        "revision_guard": AsyncMock(return_value=None),
        "collect_visual_sources": lambda _question: [],
        "has_visual_slot": lambda _question: False,
        "load_knowledge_points": AsyncMock(return_value={3: ["链表"]}),
        "input_signature": lambda *_args, **_kwargs: "input",
        "model_signature": lambda _runtime: "model",
        "cached_response": lambda *_args, **_kwargs: None,
        "cache_age": lambda _analysis: 12,
        "stale_reason": lambda *_args, **_kwargs: "input_signature",
    }
    fields.update(overrides)
    return SimpleNamespace(
        request=AnalysisPreparationRequest(**fields),
        wrong=wrong,
        question=question,
        **{"db": db, **fields},
    )


@pytest.mark.asyncio
async def test_preparation_loads_pair_materials_and_cache_miss():
    item = harness()
    preparation = await prepare_analysis(item.request)

    assert preparation.response is None
    assert preparation.wrong_question is item.wrong
    assert preparation.question is item.question
    assert preparation.answer_grounding == {
        "grounding": {
            "question_type": "single_choice",
            "content": {"stem": "stem"},
            "options": {"A": "A"},
            "correct_answer": "A",
            "user_answer": "B",
        }
    }
    assert preparation.knowledge_points == ["链表"]
    assert preparation.runtime == "runtime"
    assert (preparation.input_signature, preparation.model_signature) == (
        "input",
        "model",
    )
    item.load_knowledge_points.assert_awaited_once_with(item.db, [3])
    item.load_runtime.assert_awaited_once_with(item.db)
    item.logger.info.assert_called_once_with(
        "ai.error_analysis.cache_miss wq_id=%d user_id=%d reason=%s",
        7,
        8,
        "input_signature",
    )


@pytest.mark.asyncio
async def test_wrong_question_lookup_retains_user_filter_and_missing_raises():
    item = harness()
    item.db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    with pytest.raises(ValueError, match="错题记录不存在"):
        await prepare_analysis(item.request)
    filters = statement_filters(item.db.execute.call_args.args[0])
    assert filters == {"id": 7, "user_id": 8}


@pytest.mark.asyncio
async def test_revision_guard_short_circuits_without_material_loading():
    item = harness(revision_guard=AsyncMock(return_value={"model": "revision_guard"}))
    preparation = await prepare_analysis(item.request)
    assert preparation.response == {"model": "revision_guard"}
    item.revision_guard.assert_awaited_once_with(
        item.db, wrong_question=item.wrong, question=item.question
    )
    item.load_knowledge_points.assert_not_awaited()
    item.load_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_declared_visual_without_source_fails_closed():
    item = harness(
        collect_visual_sources=lambda _question: [],
        has_visual_slot=lambda _question: True,
    )
    preparation = await prepare_analysis(item.request)
    assert preparation.response is not None
    assert preparation.response["model"] == "vision_input_missing"
    item.load_knowledge_points.assert_not_awaited()
    item.logger.info.assert_called_once_with(
        "ai.error_analysis.image_missing wq_id=%d question_id=%d "
        "reason=declared_visual_without_source",
        7,
        3,
    )


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_projection_with_stable_log():
    cached = {"model": "cache", "from_cache": True}
    item = harness(cached_response=lambda *_args, **_kwargs: cached)
    preparation = await prepare_analysis(item.request)
    assert preparation.response is cached
    item.logger.info.assert_called_once_with(
        "ai.error_analysis.cache_hit wq_id=%d user_id=%d age_ms=%s model=%s",
        7,
        8,
        12,
        "analysis",
    )


@pytest.mark.asyncio
async def test_force_regenerate_skips_cache_without_hit_or_miss_logs():
    cache = MagicMock(side_effect=AssertionError("force must skip cached response"))
    item = harness(force_regenerate=True, cached_response=cache)
    preparation = await prepare_analysis(item.request)
    assert preparation.force is True
    assert preparation.response is None
    cache.assert_not_called()
    item.logger.info.assert_called_once_with(
        "force regenerate error analysis wq_id=%d user_id=%d", 7, 8
    )
