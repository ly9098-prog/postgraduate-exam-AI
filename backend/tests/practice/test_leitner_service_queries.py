"""Exercise real query construction without opening a database connection."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models.question import Question
from app.services import practice_service as svc

NOW = datetime(2026, 10, 27, 8)


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
@pytest.mark.parametrize("mode", ["random", "ordered"])
@pytest.mark.parametrize("exclude,days", [(False, None), (True, None), (False, 30)])
async def test_real_queries_keep_scope_repeat_window_and_layer_limits(
    monkeypatch, dialect, mode, exclude, days
):
    queries, counts, sampled = [], [], []
    monkeypatch.setattr(svc, "utcnow", lambda: NOW)

    async def execute(query):
        queries.append(query.compile(dialect=dialect))
        row = SimpleNamespace(id=len(queries))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))

    async def scalar(query):
        counts.append(query.compile(dialect=dialect))
        return 50

    def sample(query, total, limit, column):
        sampled.append((total, limit, column))
        return query.limit(limit)

    db = SimpleNamespace(execute=execute, scalar=scalar)
    fallback = AsyncMock(return_value=[])
    monkeypatch.setattr(svc, "_random_sample_query", sample)
    monkeypatch.setattr(svc, "_get_questions_v1_fallback", fallback)
    conditions = [Question.is_active, Question.subject_id.in_([2, 3])]
    result = await svc._get_questions_with_leitner(
        db,
        7,
        conditions,
        mode,
        5,
        exclude_answered=exclude,
        no_repeat_days=days,
    )
    assert [q.id for q in result] == [1, 2, 3]
    assert len(queries) == 3
    for index, query in enumerate(queries):
        sql, values = str(query), list(query.params.values())
        assert "LEFT OUTER JOIN user_question_state" in sql
        assert "user_question_state.user_id =" in sql and 7 in values
        assert "questions.is_active" in sql and [2, 3] in values
        assert "user_question_state.next_review_at IS NULL" in sql
        assert NOW + timedelta(days=[0, 1, 31][index]) in values
        assert 5 - index in values
        assert ("practice_records.user_id =" in sql) is (exclude or days is not None)
        assert ("practice_records.answered_at >=" in sql) is (days is not None)
        if days is not None:
            assert NOW - timedelta(days=days) in values
        if index:
            assert list(range(1, index + 1)) in values
    assert "last_answered_at ASC NULLS FIRST" in str(queries[2])
    if mode == "random":
        assert [(total, limit) for total, limit, _ in sampled] == [(50, 5), (50, 4)]
        assert all(column is Question.id for _, _, column in sampled)
        assert len(counts) == 2
        for count in counts:
            assert "count(" in str(count)
            assert [2, 3] in count.params.values()
            assert ("practice_records.user_id =" in str(count)) is (
                exclude or days is not None
            )
    else:
        assert sampled == counts == []
        assert "questions.id ASC" in str(queries[0])
        assert "questions.id ASC" in str(queries[1])
    fallback.assert_awaited_once_with(
        db,
        conditions,
        mode,
        2,
        user_id=7,
        exclude_answered=exclude,
        no_repeat_days=days,
        exclude_ids={1, 2, 3},
    )
