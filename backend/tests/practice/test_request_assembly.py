"""Characterize preparation order and the request passed to candidate providers."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.practice import request_assembly as assembly
from app.services.practice import request_observability as observation
from app.services.practice.request_filters import PracticeRequestFilterError
from app.services.practice.request_scope import (
    PracticeKnowledgeFilter,
    PracticeScopeNotFoundError,
    PracticeSubjectScope,
)


@pytest.fixture
def raw_request():
    return assembly.PracticeQuestionsRequest(
        user_id=7, subject_id=2, include_children=True, count=1, mode="random",
        knowledge_point=None, knowledge_point_id=None, include_descendants=False,
        exclude_answered=True, no_repeat_days=3, use_leitner=False,
        source_question_id=None, question_ids=None, start_request_id="retry",
        smart_strategy="scored", plan_token="plan", trace_header="header",
    )


@pytest.fixture
def preparation(monkeypatch):
    events = []
    scope = PracticeSubjectScope("ds", "Data structure", True, [2, 3])
    knowledge = PracticeKnowledgeFilter(None, None, None)

    async def subject(*args, **kwargs):
        events.append("subject")
        return scope

    async def resolve_knowledge(*args, **kwargs):
        events.append("knowledge")
        return knowledge

    subject_mock = AsyncMock(side_effect=subject)
    knowledge_mock = AsyncMock(side_effect=resolve_knowledge)
    monkeypatch.setattr(assembly, "resolve_subject_scope", subject_mock)
    monkeypatch.setattr(assembly, "resolve_knowledge_filter", knowledge_mock)
    monkeypatch.setattr(
        assembly, "get_log_context",
        Mock(side_effect=lambda: events.append("trace") or {}),
    )
    normalize = Mock(return_value="normalized")
    monkeypatch.setattr(assembly, "normalize_trace_id", normalize)
    return SimpleNamespace(
        events=events, subject=subject_mock, knowledge=knowledge_mock,
        normalize=normalize, scope=scope,
    )


@pytest.mark.asyncio
async def test_targeted_request_keeps_order_and_uses_exact_count(raw_request, preparation):
    prepared = await assembly.prepare_practice_request(
        object(), replace(raw_request, question_ids="9, 4"),
    )
    assert preparation.events == ["subject", "trace", "knowledge"]
    assert prepared.candidate == assembly.PracticeCandidateRequest(
        user_id=7, subject_id=2, subject_code="ds", subject_ids=[2, 3],
        count=2, mode="random", knowledge_points=None, knowledge_point_ids=None,
        include_descendants=False, exclude_answered=True, no_repeat_days=3,
        use_leitner=False, source_question_id=None, targeted_question_ids=[9, 4],
        start_request_id="retry", smart_strategy="scored",
    )
    assert prepared.issue_context == assembly.PracticeIssueContext(
        "normalized", None, None, "plan", "9, 4",
    )


@pytest.mark.asyncio
async def test_missing_subject_precedes_trace_and_invalid_filters(raw_request, preparation):
    preparation.subject.side_effect = PracticeScopeNotFoundError("missing")
    with pytest.raises(PracticeScopeNotFoundError, match="missing"):
        await assembly.prepare_practice_request(
            object(), replace(raw_request, knowledge_point="name", knowledge_point_id=3),
        )
    preparation.normalize.assert_not_called()
    preparation.knowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_filter_follows_trace_but_precedes_scope_query(raw_request, preparation):
    with pytest.raises(PracticeRequestFilterError, match="不能同时使用"):
        await assembly.prepare_practice_request(
            object(), replace(raw_request, knowledge_point="name", knowledge_point_id=3),
        )
    assert preparation.events == ["subject", "trace"]
    preparation.normalize.assert_called_once_with("header")
    preparation.knowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_not_found_precedes_invalid_target_ids(raw_request, preparation):
    preparation.knowledge.side_effect = PracticeScopeNotFoundError("knowledge missing")
    with pytest.raises(PracticeScopeNotFoundError, match="knowledge missing"):
        await assembly.prepare_practice_request(
            object(), replace(raw_request, knowledge_point_id=3, question_ids="bad"),
        )
    assert preparation.events == ["subject", "trace"]


@pytest.mark.asyncio
async def test_context_trace_is_used_without_normalizing_header(
    raw_request, preparation, monkeypatch,
):
    monkeypatch.setattr(assembly, "get_log_context", lambda: {"trace_id": "context"})
    prepared = await assembly.prepare_practice_request(object(), raw_request)
    assert prepared.issue_context.trace_id == "context"
    preparation.normalize.assert_not_called()


@pytest.mark.asyncio
async def test_scope_and_debug_payloads_preserve_contract(raw_request, preparation, monkeypatch):
    prepared = await assembly.prepare_practice_request(object(), raw_request)
    logger = Mock()
    debug = Mock()
    snapshot = Mock()
    monkeypatch.setattr(observation, "logger", logger)
    monkeypatch.setattr(observation, "debug_log", debug)
    monkeypatch.setattr(observation, "save_debug_snapshot", snapshot)
    questions = [SimpleNamespace(id=9, subject_id=2), SimpleNamespace(id=4, subject_id=3)]
    observation.log_practice_scope(
        prepared, include_children=True, mode="random", questions=questions,
    )
    assert logger.info.call_args.args[1:] == (
        2, "ds", True, False, 0, True, "聚合", [2, 3], "random", 1, 2, {2: 1, 3: 1},
    )
    observation.log_practice_response("trace", 2, questions)
    debug.assert_called_once_with(
        "trace", "API_RESPONSE",
        {"endpoint": "practice/questions", "subject_id": 2, "count": 2},
    )
    snapshot.assert_called_once_with(
        "trace", "api_response",
        {"endpoint": "practice/questions", "subject_id": 2, "question_ids": [9, 4], "total": 2},
    )
