"""Compile the actual revision and knowledge filters through both providers."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.services import practice_service as svc

NOW = datetime(2026, 10, 27, 8)


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
@pytest.mark.parametrize("leitner", [False, True])
@pytest.mark.parametrize("aggregated", [False, True])
@pytest.mark.parametrize("filters", ["names", "ids", "both"])
async def test_complete_query_keeps_latest_revision_approval_and_knowledge_filters(
    monkeypatch, dialect, leitner, aggregated, filters
):
    queries = []

    async def execute(query):
        compiled = query.compile(dialect=dialect)
        queries.append(compiled)
        scope = next(
            value
            for key, value in compiled.params.items()
            if key.startswith("subject_id_")
        )
        sid = scope[0] if isinstance(scope, list) else scope
        row = SimpleNamespace(id=sid * 10, subject_id=sid)
        return SimpleNamespace(
            scalar=lambda: 50,
            scalars=lambda: SimpleNamespace(all=lambda: [row]),
        )

    async def scalar(query):
        queries.append(query.compile(dialect=dialect))
        return 50

    monkeypatch.setattr(svc, "utcnow", lambda: NOW)
    monkeypatch.setattr(svc, "logger", Mock())
    monkeypatch.setattr(
        svc,
        "_random_sample_query",
        lambda query, total, count, column: query.limit(count),
    )
    db = SimpleNamespace(execute=execute, scalar=scalar)
    names = ["tree", "graph"] if filters in {"names", "both"} else None
    ids = [11, 12] if filters in {"ids", "both"} else None
    provider = (
        svc.get_aggregated_random_questions
        if aggregated
        else svc.get_practice_questions
    )
    rows = await provider(
        db,
        7,
        "cs",
        subject_ids=[2, 4],
        count=1,
        knowledge_points=names,
        knowledge_point_ids=ids,
        exclude_answered=True,
        no_repeat_days=30,
        use_leitner=leitner,
    )
    assert len(rows) == 1 and queries
    assert len(queries) == (4 if aggregated else 2)
    for query in queries:
        sql, values = str(query), list(query.params.values())
        assert "question_versions.version =" in sql
        assert "max(question_versions_1.version)" in sql
        assert "question_versions.subject_id = questions.subject_id" in sql
        assert "question_versions.question_type = questions.question_type" in sql
        assert "question_versions.is_active IS" in sql
        assert "questions.review_status =" in sql and "approved" in values
        assert "practice_records.user_id =" in sql and 7 in values
        assert NOW - timedelta(days=30) in values
        assert ("user_question_state" in sql) is leitner
        assert ("questions.subject_id =" in sql) is aggregated
        assert ("knowledge_points.normalized_name =" in sql) is bool(names)
        if names:
            assert "tree" in values and "graph" in values
            assert sql.count("knowledge_points.normalized_name =") == 2
        assert ("question_knowledge_points.knowledge_point_id IN" in sql) is bool(ids)
        if ids:
            assert ids in values
            assert "knowledge_points.is_active IS" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 50, 100])
@pytest.mark.parametrize("leitner", [False, True])
async def test_candidate_pool_count_is_not_clamped(monkeypatch, count, leitner):
    async def load(*args, **kwargs):
        assert args[-1] == count
        return []

    monkeypatch.setattr(svc, "_get_questions_with_leitner", load)
    monkeypatch.setattr(svc, "_get_questions_v1_fallback", load)
    await svc.get_practice_questions(
        object(),
        7,
        "cs",
        subject_ids=[2],
        count=count,
        use_leitner=leitner,
    )
    await svc.get_aggregated_random_questions(
        object(),
        7,
        "cs",
        subject_ids=[2],
        count=count,
        use_leitner=leitner,
    )


@pytest.mark.asyncio
async def test_sequential_mode_uses_live_constant_and_ignores_repeat_window(
    monkeypatch,
):
    rows = [object()]

    async def sequential(*args, **kwargs):
        assert kwargs == {
            "user_id": 7,
            "subject_id": 2,
            "subject_ids": [2],
            "count": 100,
            "knowledge_points": ["tree"],
        }
        return rows, {}

    monkeypatch.setattr(svc, "SEQUENTIAL_MODE", "custom-sequential")
    monkeypatch.setattr(svc, "get_sequential_practice_questions", sequential)
    result = await svc.get_practice_questions(
        object(),
        7,
        "cs",
        subject_ids=[2],
        count=100,
        mode="custom-sequential",
        knowledge_points=["tree"],
        knowledge_point_ids=[11],
        use_leitner=True,
        exclude_answered=True,
        no_repeat_days=30,
    )
    assert result is rows
