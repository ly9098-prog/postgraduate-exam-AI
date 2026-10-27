"""Characterize scope, eligibility and dispatch at the basic practice entry."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import and_
from sqlalchemy.dialects import postgresql, sqlite

from app.models.question import Question
from app.services import practice_service as svc


@pytest.fixture
def selection_ports(monkeypatch):
    state = SimpleNamespace(
        db=object(),
        resolved=[8],
        rows=[object()],
        events=[],
        calls=[],
        revisions=[],
        id_condition=True,
    )

    async def resolve(db, code):
        assert db is state.db and code == "cs"
        state.events.append("resolve")
        return state.resolved

    def revision(ids):
        state.events.append("revision")
        condition = Question.difficulty >= 1
        state.revisions.append((ids, condition))
        return condition

    def names(values):
        state.events.append(("names", values))
        return [Question.question_type == "single_choice"]

    def ids(values):
        state.events.append(("ids", values))
        return Question.id.in_(values) if state.id_condition else None

    def provider(name):
        async def load(*args, **kwargs):
            state.events.append(name)
            state.calls.append((name, args, kwargs))
            return (state.rows, {"cursor": 99}) if name == "sequential" else state.rows

        return load

    monkeypatch.setattr(svc, "resolve_subject_ids", resolve)
    monkeypatch.setattr(svc, "_practice_revision_scope_condition", revision)
    monkeypatch.setattr(svc, "kp_exact_conditions", names)
    monkeypatch.setattr(svc, "kp_id_any_condition", ids)
    monkeypatch.setattr(
        svc, "get_sequential_practice_questions", provider("sequential")
    )
    monkeypatch.setattr(svc, "_get_questions_with_leitner", provider("leitner"))
    monkeypatch.setattr(svc, "_get_questions_v1_fallback", provider("v1"))
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["random", "ordered", "sequential"])
@pytest.mark.parametrize("leitner", [False, True])
@pytest.mark.parametrize("scope", [None, [], [2], [2, 3]])
@pytest.mark.parametrize(
    "filters", ["none", "names", "ids", "both", "empty", "no-id-condition"]
)
async def test_scope_filters_and_dispatch(
    selection_ports, mode, leitner, scope, filters
):
    state = selection_ports
    names = ["tree", "graph"] if filters in {"names", "both"} else None
    kp_ids = [11, 12] if filters in {"ids", "both", "no-id-condition"} else None
    if filters == "empty":
        names, kp_ids = [], []
    state.id_condition = filters != "no-id-condition"
    ids = state.resolved if scope is None else scope
    kwargs = dict(
        count=9,
        mode=mode,
        knowledge_points=names,
        knowledge_point_ids=kp_ids,
        exclude_answered=True,
        no_repeat_days=30,
        use_leitner=leitner,
        subject_ids=scope,
    )
    if mode == "sequential" and len(ids) != 1:
        with pytest.raises(ValueError, match="顺序练习仅支持单一具体科目"):
            await svc.get_practice_questions(state.db, 7, "cs", **kwargs)
        assert state.calls == []
    else:
        result = await svc.get_practice_questions(state.db, 7, "cs", **kwargs)
        assert result is state.rows
        name, args, passed = state.calls[0]
        expected_name = (
            "sequential" if mode == "sequential" else "leitner" if leitner else "v1"
        )
        assert name == expected_name
        if mode == "sequential":
            assert args == (state.db,)
            assert passed == {
                "user_id": 7,
                "subject_id": ids[0],
                "subject_ids": ids,
                "count": 9,
                "knowledge_points": names,
            }
            assert passed["subject_ids"] is ids
            assert passed["knowledge_points"] is names
        else:
            assert args[0] is state.db
            assert len(args) == (5 if leitner else 4)
            if leitner:
                assert args[1] == 7
            conditions = args[2] if leitner else args[1]
            assert args[-2:] == (mode, 9)
            assert passed == dict(
                **({} if leitner else {"user_id": 7}),
                exclude_answered=True,
                no_repeat_days=30,
            )
            assert conditions[0] is Question.is_active
            assert conditions[2] is state.revisions[0][1]
            assert len(conditions) == 3 + bool(names) + (
                bool(kp_ids) and state.id_condition
            )
            for dialect in (sqlite.dialect(), postgresql.dialect()):
                compiled = and_(*conditions).compile(dialect=dialect)
                sql, values = str(compiled), list(compiled.params.values())
                assert "questions.subject_id IN" in sql and ids in values
                assert "questions.difficulty >=" in sql
                assert ("questions.question_type =" in sql) is bool(names)
                assert ("questions.id IN" in sql) is (
                    bool(kp_ids) and state.id_condition
                )
    assert state.revisions[0][0] is ids
    expected = (["resolve"] if scope is None else []) + ["revision"]
    if names:
        expected.append(("names", names))
    if kp_ids:
        expected.append(("ids", kp_ids))
    if state.calls:
        expected.append(state.calls[0][0])
    assert state.events == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("leitner", [False, True])
@pytest.mark.parametrize("exclude,days", [(False, None), (True, None), (False, 30)])
async def test_repeat_options_are_forwarded(selection_ports, leitner, exclude, days):
    state = selection_ports
    await svc.get_practice_questions(
        state.db,
        7,
        "cs",
        subject_ids=[2],
        use_leitner=leitner,
        exclude_answered=exclude,
        no_repeat_days=days,
    )
    _, args, kwargs = state.calls[0]
    assert args[-2:] == ("random", 20)
    assert kwargs == dict(
        **({} if leitner else {"user_id": 7}),
        exclude_answered=exclude,
        no_repeat_days=days,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    [
        "resolve_subject_ids",
        "_practice_revision_scope_condition",
        "kp_exact_conditions",
        "kp_id_any_condition",
        "_get_questions_with_leitner",
        "_get_questions_v1_fallback",
        "get_sequential_practice_questions",
    ],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_preparation_and_provider_errors_propagate(
    monkeypatch, selection_ports, stage, error_type
):
    state = selection_ports
    error = error_type("synthetic selection failure")

    def fail(*args, **kwargs):
        raise error

    async def async_fail(*args, **kwargs):
        raise error

    is_async = stage not in {
        "_practice_revision_scope_condition",
        "kp_exact_conditions",
        "kp_id_any_condition",
    }
    monkeypatch.setattr(svc, stage, async_fail if is_async else fail)
    with pytest.raises(error_type) as caught:
        await svc.get_practice_questions(
            state.db,
            7,
            "cs",
            knowledge_points=["tree"],
            knowledge_point_ids=[11],
            use_leitner=stage != "_get_questions_v1_fallback",
            mode="sequential"
            if stage == "get_sequential_practice_questions"
            else "random",
        )
    assert caught.value is error
    assert state.calls == []


@pytest.mark.asyncio
async def test_resolver_and_filter_callbacks_remain_live(monkeypatch, selection_ports):
    state = selection_ports
    seen = []
    names = ["tree"]
    kp_ids = [11]

    async def provider(*args, **kwargs):
        seen.append("replacement-provider")
        return state.rows

    def replacement_ids(values):
        assert values is kp_ids
        seen.append("replacement-ids")
        return None

    def replacement_names(values):
        assert values is names
        seen.append("replacement-names")
        monkeypatch.setattr(svc, "kp_id_any_condition", replacement_ids)
        return []

    async def resolve(*args):
        seen.append("resolve")
        monkeypatch.setattr(svc, "kp_exact_conditions", replacement_names)
        monkeypatch.setattr(svc, "_get_questions_with_leitner", provider)
        return state.resolved

    monkeypatch.setattr(svc, "resolve_subject_ids", resolve)
    result = await svc.get_practice_questions(
        state.db,
        7,
        "cs",
        knowledge_points=names,
        knowledge_point_ids=kp_ids,
    )
    assert result is state.rows
    assert seen == [
        "resolve",
        "replacement-names",
        "replacement-ids",
        "replacement-provider",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["resolve_subject_ids", "_get_questions_with_leitner"]
)
async def test_actual_task_cancel_stops_selection(monkeypatch, selection_ports, stage):
    state = selection_ports
    entered = asyncio.Event()
    finalized = []

    async def pending(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    monkeypatch.setattr(svc, stage, pending)
    task = asyncio.create_task(svc.get_practice_questions(state.db, 7, "cs"))
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
    assert state.calls == []
