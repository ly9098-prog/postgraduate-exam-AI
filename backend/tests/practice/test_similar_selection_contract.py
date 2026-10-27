"""Pin scope, truncation and live supplement assembly at the similar entry."""

import asyncio

import pytest
from sqlalchemy import and_
from sqlalchemy.dialects import postgresql, sqlite

from app.services import practice_service as svc
from tests.similar_selection_support import SimilarHarness


@pytest.fixture
def harness(monkeypatch):
    return SimilarHarness(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, [], [8], [8, 9]])
@pytest.mark.parametrize("count", [-1, 0, 1, 3, 4, 20, 80])
@pytest.mark.parametrize("leitner", [False, True])
async def test_scope_count_identity_and_candidate_only_scheduling(
    harness, scope, count, leitner
):
    state = harness
    expected_scope = state.scope if scope is None else scope
    questions, metadata = await state.run(
        subject_ids=scope, count=count, use_leitner=leitner
    )
    request = state.requests[0]
    assert request.db is state.db and request.user_id == 7
    assert request.source_question_id == 42
    assert request.scope_ids is expected_scope
    assert request.excluded_sub is state.exclusions[0]
    assert request.logger is state.logger
    assert request.search_similar is state.vector.search_similar_questions
    assert request.revision_condition == state.revision
    assert metadata is state.metadata and 99 in metadata
    prefix = ["resolve"] if scope is None else []
    if count <= len(state.questions):
        assert questions == state.questions[:count]
        assert questions is not state.questions
        assert state.events == prefix + ["exclude", "recall"]
        assert state.fill_calls == []
    else:
        assert questions == state.questions + state.fill
        assert questions is not state.questions and questions is not state.fill
        assert state.events == prefix + [
            "exclude",
            "recall",
            "revision",
            "exclude",
            "fill",
            "metadata",
        ]
        db, conditions, need, sample = state.fill_calls[0]
        assert db is state.db and need == count - len(state.questions)
        assert sample is state.random_sample
        assert conditions[2] is state.revision_calls[0][1]
        assert state.revision_calls[0][0] is expected_scope
        assert len(conditions) == 5
        assert [q.id for q in questions[:3]] == [4, 2, 4]
        assert metadata[7] == {
            "recommend_reason": "规则补齐",
            "recommend_score": None,
            "strategy": "fallback",
            "similarity": None,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exclude_answered,no_repeat_days",
    [(False, None), (True, None), (False, 0), (True, 30)],
)
async def test_exclusion_is_recomputed_with_original_options(
    harness, exclude_answered, no_repeat_days
):
    await harness.run(
        count=5, exclude_answered=exclude_answered, no_repeat_days=no_repeat_days
    )
    assert (
        harness.exclude_options
        == [
            dict(
                user_id=7,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
            )
        ]
        * 2
    )
    assert harness.exclusions[0] is not harness.exclusions[1]
    condition = harness.fill_calls[0][1][-1]
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(
            condition.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        )
        assert "101" in sql and "100" not in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [[], [8], [8, 9]])
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
async def test_supplement_sql_keeps_active_revision_scope_and_source_exclusion(
    harness, scope, dialect
):
    await harness.run(count=5, subject_ids=scope)
    conditions = harness.fill_calls[0][1]
    sql = str(
        and_(*conditions).compile(
            dialect=dialect, compile_kwargs={"literal_binds": True}
        )
    )
    assert "questions.is_active" in sql and "questions.difficulty >= 2" in sql
    assert "questions.subject_id IN" in sql and "questions.id NOT IN" in sql
    excluded = set(conditions[3].right.value)
    assert excluded == {2, 4, 42}
    assert conditions[1].right.value == scope


@pytest.mark.asyncio
async def test_absent_exclusion_leaves_four_supplement_filters(monkeypatch, harness):
    monkeypatch.setattr(svc, "_build_excluded_question_subquery", lambda **kw: None)
    await harness.run(count=5)
    assert harness.requests[0].excluded_sub is None
    assert len(harness.fill_calls[0][1]) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["resolve", "exclude", "recall", "revision", "fill", "metadata"]
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_service_port_failures_and_cancellation_propagate(
    harness, stage, error_type
):
    error = error_type("synthetic similar failure")
    harness.errors[stage] = error
    with pytest.raises(error_type) as caught:
        await harness.run(count=5)
    assert caught.value is error
    assert harness.events[-1] == stage
