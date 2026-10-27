"""Pin aggregated random eligibility, bucket arguments and callback timing."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import and_
from sqlalchemy.dialects import postgresql, sqlite

from app.models.question import Question
from app.services import practice_service as svc


@pytest.fixture
def bucket_ports(monkeypatch):
    state = SimpleNamespace(
        db=object(),
        calls=[],
        revisions=[],
        filters=[],
        merged=None,
        merge_calls=[],
        logger=Mock(),
        rows={
            2: [SimpleNamespace(id=21, subject_id=2)],
            3: [],
            4: [SimpleNamespace(id=41, subject_id=4)],
        },
    )

    def revision(ids):
        condition = Question.difficulty >= ids[0]
        state.revisions.append((ids, condition))
        return condition

    def names(values):
        state.filters.append(("names", values))
        return [Question.question_type == "single_choice"]

    def ids(values):
        state.filters.append(("ids", values))
        return Question.id.in_(values)

    def provider(name):
        async def load(*args, **kwargs):
            conditions = args[2] if name == "leitner" else args[1]
            sid = conditions[1].right.value
            state.calls.append((name, args, kwargs, conditions))
            return state.rows[sid]

        return load

    original_merge = svc._round_robin_merge

    def merge(*args, **kwargs):
        state.merge_calls.append((args, kwargs))
        state.merged = original_merge(*args, **kwargs)
        return state.merged

    monkeypatch.setattr(svc, "_practice_revision_scope_condition", revision)
    monkeypatch.setattr(svc, "kp_exact_conditions", names)
    monkeypatch.setattr(svc, "kp_id_any_condition", ids)
    monkeypatch.setattr(svc, "_get_questions_with_leitner", provider("leitner"))
    monkeypatch.setattr(svc, "_get_questions_v1_fallback", provider("v1"))
    monkeypatch.setattr(svc, "_round_robin_merge", merge)
    monkeypatch.setattr(svc, "logger", state.logger)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [[], [2], [2, 3, 4], [2, 2]])
@pytest.mark.parametrize("leitner", [False, True])
@pytest.mark.parametrize(
    "names,ids", [(None, None), (["tree"], None), (None, [11]), (["tree"], [11])]
)
async def test_bucket_scope_filters_and_provider_arguments(
    bucket_ports, scope, leitner, names, ids
):
    state = bucket_ports
    result = await svc.get_aggregated_random_questions(
        state.db,
        7,
        "cs",
        scope,
        count=9,
        knowledge_points=names,
        knowledge_point_ids=ids,
        exclude_answered=True,
        no_repeat_days=30,
        use_leitner=leitner,
    )
    assert len(state.calls) == len(scope)
    for index, (name, args, kwargs, conditions) in enumerate(state.calls):
        sid = scope[index]
        assert name == ("leitner" if leitner else "v1")
        assert args[0] is state.db and args[-2:] == ("random", 9)
        assert len(args) == (5 if leitner else 4)
        if leitner:
            assert args[1] == 7
        assert kwargs == dict(
            **({} if leitner else {"user_id": 7}),
            exclude_answered=True,
            no_repeat_days=30,
        )
        assert state.revisions[index][0] == [sid]
        assert conditions[0] is Question.is_active
        assert conditions[2] is state.revisions[index][1]
        assert len(conditions) == 3 + bool(names) + bool(ids)
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            compiled = and_(*conditions).compile(dialect=dialect)
            sql, values = str(compiled), list(compiled.params.values())
            assert "questions.subject_id =" in sql and sid in values
            assert "questions.subject_id IN" not in sql
            assert ("questions.question_type =" in sql) is bool(names)
            assert ("questions.id IN" in sql) is bool(ids)
    expected_filters = []
    for _ in scope:
        if names:
            expected_filters.append(("names", names))
        if ids:
            expected_filters.append(("ids", ids))
    assert state.filters == expected_filters
    if scope:
        assert result is state.merged
        assert {q.id for q in result} == {
            q.id for sid in scope for q in state.rows[sid]
        }
        (buckets, count), kwargs = state.merge_calls[0]
        expected_buckets = [state.rows[sid] for sid in scope if state.rows[sid]]
        assert len(buckets) == len(expected_buckets)
        assert all(
            left is right for left, right in zip(buckets, expected_buckets, strict=True)
        )
        assert count == 9 and kwargs == {"randomize_order": True}
    else:
        assert result == [] and state.merge_calls == []
    state.logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_aggregator_receives_original_ports_and_bucket_uses_supplied_db(
    monkeypatch, bucket_ports
):
    state = bucket_ports
    scope, names, ids = [2], ["tree"], [11]
    alternate_db = object()
    merge = svc._round_robin_merge

    async def aggregator(request):
        assert request.db is state.db and request.subject_ids is scope
        assert request.subject_code == "cs" and request.count == 9
        assert request.logger is state.logger and request.merge is merge
        rows = await request.load_bucket(alternate_db, 4, 3)
        assert rows is state.rows[4]
        return rows

    monkeypatch.setattr(svc, "run_aggregated_random", aggregator)
    result = await svc.get_aggregated_random_questions(
        state.db,
        7,
        "cs",
        scope,
        count=9,
        knowledge_points=names,
        knowledge_point_ids=ids,
    )
    assert result is state.rows[4]
    _, args, kwargs, _ = state.calls[0]
    assert args[0] is alternate_db and args[-2:] == ("random", 3)
    assert kwargs == {"exclude_answered": False, "no_repeat_days": None}
    assert state.revisions[0][0] == [4]
    assert state.filters[0][1] is names and state.filters[1][1] is ids


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_second_bucket_observes_replaced_provider(
    monkeypatch, bucket_ports, error_type
):
    state = bucket_ports
    error = error_type("second bucket")
    calls = []

    async def replacement(*args, **kwargs):
        calls.append("replacement")
        raise error

    async def initial(*args, **kwargs):
        calls.append("initial")
        monkeypatch.setattr(svc, "_get_questions_with_leitner", replacement)
        return state.rows[2]

    monkeypatch.setattr(svc, "_get_questions_with_leitner", initial)
    with pytest.raises(error_type) as caught:
        await svc.get_aggregated_random_questions(state.db, 7, "cs", [2, 4])
    assert caught.value is error and calls == ["initial", "replacement"]
    assert state.merge_calls == []
    state.logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_bucket_cancel_does_not_merge_or_log(monkeypatch, bucket_ports):
    state = bucket_ports
    entered = asyncio.Event()
    finalized = []

    async def pending(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    monkeypatch.setattr(svc, "_get_questions_with_leitner", pending)
    task = asyncio.create_task(
        svc.get_aggregated_random_questions(state.db, 7, "cs", [2, 4])
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert finalized == [True]
    assert state.merge_calls == []
    state.logger.info.assert_not_called()
