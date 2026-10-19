"""Schedule guard preserves due-only merge behavior without issuing batches."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.practice import candidate_schedule as schedule
from app.services.practice.candidate_selection import PracticeCandidateRequest


def _request(**changes):
    values = dict(
        user_id=7,
        subject_id=2,
        subject_code="ds",
        subject_ids=[2],
        count=3,
        mode="smart",
        knowledge_points=["tree"],
        knowledge_point_ids=[9],
        include_descendants=False,
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=True,
        source_question_id=None,
        targeted_question_ids=[],
        start_request_id=None,
        smart_strategy="scored",
    )
    return PracticeCandidateRequest(**(values | changes))


def _rows(*ids):
    return [SimpleNamespace(id=qid) for qid in ids]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,enabled,ids",
    [
        ("random", True, [1]),
        ("sequential", True, [1]),
        ("smart", False, [1]),
        ("similar", False, [1]),
        ("smart", True, []),
    ],
)
async def test_inapplicable_guards_do_not_query(monkeypatch, mode, enabled, ids):
    due = AsyncMock()
    monkeypatch.setattr(schedule.question_review_service, "get_due_question_ids", due)
    rows = _rows(*ids)
    result = await schedule.filter_due_candidates(
        None, _request(use_leitner=enabled), rows, mode=mode
    )
    assert result is rows
    due.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["smart", "similar"])
async def test_due_guard_merges_unique_due_fallback_in_order(monkeypatch, mode):
    due = AsyncMock(side_effect=[{1}, {1, 3, 5, 6}])
    fallback = AsyncMock(return_value=_rows(1, 2, 3, 3, 5, 6))
    monkeypatch.setattr(schedule.question_review_service, "get_due_question_ids", due)
    monkeypatch.setattr(schedule.svc, "get_practice_questions", fallback)
    request = _request()
    result = await schedule.filter_due_candidates(None, request, _rows(1, 2), mode=mode)
    assert [row.id for row in result] == [1, 3, 5]
    fallback.assert_awaited_once_with(
        db=None,
        **request.query_filters(),
        count=3,
        mode="random",
        knowledge_points=["tree"],
        knowledge_point_ids=[9],
    )
    assert due.await_args_list[0].args == (None, 7, [1, 2])
    assert due.await_args_list[1].args == (None, 7, [1, 2, 3, 3, 5, 6])


@pytest.mark.asyncio
async def test_due_overflow_truncates_without_fallback(monkeypatch):
    due = AsyncMock(return_value={1, 2, 3})
    fallback = AsyncMock()
    monkeypatch.setattr(schedule.question_review_service, "get_due_question_ids", due)
    monkeypatch.setattr(schedule.svc, "get_practice_questions", fallback)
    result = await schedule.filter_due_candidates(
        None, _request(count=2), _rows(3, 1, 2), mode="smart"
    )
    assert [row.id for row in result] == [3, 1]
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_due_fallback_returns_short_batch(monkeypatch):
    due = AsyncMock(side_effect=[set(), set()])
    fallback = AsyncMock(return_value=_rows(2))
    monkeypatch.setattr(schedule.question_review_service, "get_due_question_ids", due)
    monkeypatch.setattr(schedule.svc, "get_practice_questions", fallback)
    result = await schedule.filter_due_candidates(
        None, _request(), _rows(1), mode="smart"
    )
    assert result == []


@pytest.mark.asyncio
async def test_existing_duplicates_still_belong_to_final_issue_guard(monkeypatch):
    due = AsyncMock(return_value={1})
    monkeypatch.setattr(schedule.question_review_service, "get_due_question_ids", due)
    result = await schedule.filter_due_candidates(
        None, _request(count=2), _rows(1, 1), mode="smart"
    )
    assert [row.id for row in result] == [1, 1]
