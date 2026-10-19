"""Provider contracts independent of FastAPI and revision issuance."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.services.practice import candidate_selection as selection


@pytest.fixture
def candidate_request():
    return selection.PracticeCandidateRequest(
        user_id=7,
        subject_id=2,
        subject_code="ds",
        subject_ids=[2],
        count=5,
        mode="random",
        knowledge_points=["tree"],
        knowledge_point_ids=None,
        include_descendants=False,
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=True,
        source_question_id=None,
        targeted_question_ids=[],
        start_request_id=None,
        smart_strategy="scored",
    )


@pytest.fixture
def providers(monkeypatch):
    mocks = {}
    for name in (
        "get_targeted_practice_questions",
        "get_practice_questions",
        "get_aggregated_random_questions",
        "get_knowledge_scope_practice_questions",
        "get_similar_practice_questions",
        "get_smart_practice_questions",
        "get_aggregated_smart_questions",
        "get_sequential_practice_questions",
    ):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(selection.svc, name, mocks[name])
    monkeypatch.setattr(selection, "uuid4", lambda: UUID(int=1))
    return mocks


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [[2], [1, 2]])
@pytest.mark.parametrize("count", [1, 5, 20, 50])
@pytest.mark.parametrize("canonical", [False, True])
async def test_random_provider_arguments(
    candidate_request, providers, scope, count, canonical
):
    request = replace(
        candidate_request,
        subject_ids=scope,
        count=count,
        knowledge_point_ids=[9] if canonical else None,
    )
    name = (
        "get_aggregated_random_questions"
        if len(scope) > 1
        else "get_practice_questions"
    )
    rows = [SimpleNamespace(id=1)]
    providers[name].return_value = rows
    result = await selection.select_practice_candidates(None, request)
    expected = dict(
        db=None,
        **request.query_filters(),
        count=min(100, count + max(5, count // 2)),
        knowledge_points=None if canonical else ["tree"],
        knowledge_point_ids=[9] if canonical else None,
    )
    if len(scope) == 1:
        expected["mode"] = "random"
    providers[name].assert_awaited_once_with(**expected)
    assert result.questions is rows
    assert result.mode == "random" and result.request_id is None
    assert sum(mock.await_count for mock in providers.values()) == 1


@pytest.mark.asyncio
async def test_chapter_pool_uses_requested_count(candidate_request, providers):
    request = replace(
        candidate_request,
        subject_ids=[1, 2],
        include_descendants=True,
        knowledge_point_ids=[9, 10],
    )
    providers["get_knowledge_scope_practice_questions"].return_value = []
    await selection.select_practice_candidates(None, request)
    providers["get_knowledge_scope_practice_questions"].assert_awaited_once_with(
        db=None,
        **request.query_filters(),
        count=5,
        knowledge_point_ids=[9, 10],
    )
    assert sum(mock.await_count for mock in providers.values()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [[2], [1, 2]])
async def test_smart_dispatch_keeps_metadata(candidate_request, providers, scope):
    request = replace(candidate_request, subject_ids=scope, mode="smart")
    name = (
        "get_aggregated_smart_questions"
        if len(scope) > 1
        else "get_smart_practice_questions"
    )
    metadata = {1: {"recommend_score": 0.8}}
    providers[name].return_value = ([SimpleNamespace(id=1)], metadata)
    result = await selection.select_practice_candidates(None, request)
    providers[name].assert_awaited_once_with(
        db=None,
        **request.query_filters(),
        count=5,
        request_id=result.request_id,
        smart_strategy="scored",
    )
    assert result.metadata is metadata and result.request_id
    assert sum(mock.await_count for mock in providers.values()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [[2], [1, 2]])
async def test_similar_without_source_uses_legacy_leaf_fallback(
    candidate_request, providers, scope
):
    request = replace(candidate_request, mode="similar", subject_ids=scope)
    providers["get_practice_questions"].return_value = []
    result = await selection.select_practice_candidates(None, request)
    providers["get_practice_questions"].assert_awaited_once_with(
        db=None,
        **request.query_filters(),
        count=10,
        mode="random",
        knowledge_points=["tree"],
    )
    assert result.mode == "random" and result.request_id is None
    assert sum(mock.await_count for mock in providers.values()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("logging_fails", [False, True])
async def test_similar_logging_is_best_effort(
    candidate_request, providers, monkeypatch, logging_fails
):
    request = replace(candidate_request, mode="similar", source_question_id=42)
    metadata = {
        1: {"recommend_score": 0.8, "similarity": 0.5, "recommend_reason": "reason"}
    }
    providers["get_similar_practice_questions"].return_value = (
        [SimpleNamespace(id=1)],
        metadata,
    )
    log = AsyncMock(
        side_effect=RuntimeError("log unavailable") if logging_fails else None
    )
    monkeypatch.setattr(
        selection.recommendation_log_service, "create_recommendation_logs_isolated", log
    )
    result = await selection.select_practice_candidates(None, request)
    providers["get_similar_practice_questions"].assert_awaited_once_with(
        db=None,
        **request.query_filters(),
        source_question_id=42,
        count=5,
    )
    log.assert_awaited_once_with(
        db=None,
        user_id=7,
        recommendations=[
            {
                "question_id": 1,
                "subject": "ds",
                "recommend_score": 0.8,
                "similarity": 0.5,
                "reason": "reason",
            }
        ],
        scene="similar",
        strategy="vector_plus_rule",
        request_id=result.request_id,
        source_question_id=42,
    )
    assert result.metadata is metadata and result.mode == "similar"


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_ids", [[3, 1], [3], [1, 3]])
async def test_targeted_preserves_exact_order(
    candidate_request, providers, returned_ids
):
    request = replace(candidate_request, targeted_question_ids=[3, 1])
    rows = [SimpleNamespace(id=qid) for qid in returned_ids]
    providers["get_targeted_practice_questions"].return_value = rows
    if returned_ids == [3, 1]:
        result = await selection.select_practice_candidates(None, request)
        assert result.questions is rows
    else:
        with pytest.raises(selection.PracticeCandidateError, match="定向题目已失效"):
            await selection.select_practice_candidates(None, request)
    providers["get_targeted_practice_questions"].assert_awaited_once_with(
        None,
        question_ids=[3, 1],
        subject_ids=[2],
    )
    assert sum(mock.await_count for mock in providers.values()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start_id, expected",
    [
        (None, "seqstart:7:00000000000000000000000000000001"),
        (" retry ", "retry"),
        (" ", ""),
    ],
)
async def test_sequential_uses_only_progress_filters(
    candidate_request, providers, start_id, expected
):
    request = replace(candidate_request, mode="sequential", start_request_id=start_id)
    progress = {"cursor": 3}
    providers["get_sequential_practice_questions"].return_value = ([], progress)
    result = await selection.select_practice_candidates(None, request)
    providers["get_sequential_practice_questions"].assert_awaited_once_with(
        db=None,
        user_id=7,
        subject_id=2,
        subject_ids=[2],
        count=5,
        knowledge_points=["tree"],
        reservation_request_id=expected,
    )
    assert result.sequential_progress is progress
    assert result.reservation_request_id == expected
    assert result.request_id is None


@pytest.mark.asyncio
async def test_sequential_value_error_is_domain_error(candidate_request, providers):
    request = replace(candidate_request, mode="sequential")
    providers["get_sequential_practice_questions"].side_effect = ValueError(
        "reservation conflict"
    )
    with pytest.raises(selection.PracticeCandidateError, match="reservation conflict"):
        await selection.select_practice_candidates(None, request)


@pytest.mark.asyncio
async def test_unexpected_provider_failure_propagates(candidate_request, providers):
    providers["get_practice_questions"].side_effect = RuntimeError(
        "database unavailable"
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        await selection.select_practice_candidates(None, candidate_request)
