"""Submission protocol, cache ordering and retained practice request contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.v1 import practice as api
from app.schemas.practice import BatchSubmitRequest, SequentialPracticeResetRequest

pytestmark = pytest.mark.asyncio


def request():
    return BatchSubmitRequest(
        batch_token="synthetic-test-batch-token",
        answers=[{"question_id": 8, "user_answer": "A", "used_time": 2}],
        skipped_question_ids=[9],
        session={
            "request_id": "practice-test-request",
            "subject_id": 2,
            "mode": "sequential",
            "started_at": "2026-10-30T00:00:00Z",
            "finished_at": "2026-10-30T00:00:02Z",
            "duration_sec": 2,
            "question_count": 2,
            "answered_count": 1,
        },
    )


def result():
    return {
        "results": [{"question_id": 8, "is_correct": True, "correct_answer": "A"}],
        "total_correct": 1,
        "total_wrong": 0,
    }


@pytest.fixture
def setup(monkeypatch):
    trace = []
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    user = SimpleNamespace(id=3)

    async def submit(**kwargs):
        trace.append(("submit", kwargs))
        return result()

    async def delete(key):
        trace.append(("delete", key))

    monkeypatch.setattr(api, "get_log_context", lambda: {"trace_id": "context-trace"})
    monkeypatch.setattr(api, "normalize_trace_id", Mock(return_value="header-trace"))
    monkeypatch.setattr(api, "debug_log", lambda *args: trace.append(("debug", args)))
    monkeypatch.setattr(
        api, "save_debug_snapshot", lambda *args: trace.append(("snapshot", args))
    )
    monkeypatch.setattr(api.svc, "batch_submit_answers", AsyncMock(side_effect=submit))
    monkeypatch.setattr(api.cache, "delete", AsyncMock(side_effect=delete))
    monkeypatch.setattr(api, "logger", SimpleNamespace(warning=Mock()))
    return SimpleNamespace(db=db, user=user, trace=trace)


async def call(setup, data=None):
    return await api.batch_submit(
        data=data if data is not None else request(),
        x_trace_id="header",
        db=setup.db,
        current_user=setup.user,
    )


async def test_submit_protocol_projection_and_effect_order(setup):
    data = request()
    response = await call(setup, data)
    assert [event[0] for event in setup.trace] == [
        "debug",
        "snapshot",
        "submit",
        "delete",
        "delete",
        "delete",
        "snapshot",
    ]
    assert setup.trace[0] == (
        "debug",
        (
            "context-trace",
            "SUBMIT",
            {"endpoint": "practice/batch-submit", "answer_count": 1},
        ),
    )
    assert setup.trace[1] == (
        "snapshot",
        ("context-trace", "submit_before", {"question_ids": [8]}),
    )
    kwargs = setup.trace[2][1]
    assert kwargs == {
        "db": setup.db,
        "user_id": 3,
        "answers": [answer.model_dump() for answer in data.answers],
        "session_meta": data.session.model_dump(),
        "skipped_question_ids": [9],
        "batch_token": data.batch_token,
    }
    assert kwargs["skipped_question_ids"] is data.skipped_question_ids
    assert [event[1] for event in setup.trace[3:6]] == [
        "practice:stats:3:*",
        "stats:*:3*",
        "review:*:3*",
    ]
    assert setup.trace[-1] == (
        "snapshot",
        (
            "context-trace",
            "submit_after",
            {
                "total_correct": 1,
                "total_wrong": 0,
                "total_skipped": 0,
                "result_count": 1,
            },
        ),
    )
    assert response.trace_id == "context-trace"
    assert response.total_skipped == 0 and response.knowledge_session is None
    assert response.results[0].question_id == 8
    setup.db.commit.assert_not_awaited()
    setup.db.rollback.assert_not_awaited()
    api.normalize_trace_id.assert_not_called()


@pytest.mark.parametrize("context", [None, "", 0, False, 17])
async def test_trace_context_fallback_and_string_conversion(
    setup, monkeypatch, context
):
    monkeypatch.setattr(api, "get_log_context", lambda: {"trace_id": context})
    response = await call(setup)
    assert response.trace_id == (str(context) if context else "header-trace")
    assert api.normalize_trace_id.call_count == (0 if context else 1)


@pytest.mark.parametrize(
    "error_name,status,code",
    [
        ("PracticeBatchTokenError", 400, "PRACTICE_BATCH_INVALID"),
        ("PracticeSubmissionConflictError", 409, "PRACTICE_SUBMISSION_CONFLICT"),
        ("ValueError", 400, "PRACTICE_PAYLOAD_INVALID"),
    ],
)
async def test_submit_service_error_mapping_is_terminal(
    setup, error_name, status, code
):
    cls = ValueError if error_name == "ValueError" else getattr(api.svc, error_name)
    error = cls("synthetic rejection")
    api.svc.batch_submit_answers.side_effect = error
    with pytest.raises(HTTPException) as caught:
        await call(setup)
    assert caught.value.status_code == status
    assert caught.value.detail == {"error_code": code, "retryable": False}
    assert caught.value.__context__ is error
    api.logger.warning.assert_called_once()
    assert api.logger.warning.call_args.args[1:] == (3, "context-trace", error)
    api.cache.delete.assert_not_awaited()
    assert len(setup.trace) == 2
    setup.db.commit.assert_not_awaited()
    setup.db.rollback.assert_not_awaited()


@pytest.mark.parametrize("error", [RuntimeError("service"), asyncio.CancelledError()])
async def test_unhandled_service_errors_and_cancellation_propagate(setup, error):
    api.svc.batch_submit_answers.side_effect = error
    with pytest.raises(type(error)) as caught:
        await call(setup)
    assert caught.value is error
    api.cache.delete.assert_not_awaited()
    api.logger.warning.assert_not_called()


@pytest.mark.parametrize("failed_step", [0, 1, 2])
@pytest.mark.parametrize("error_cls", [ValueError, asyncio.CancelledError])
async def test_cache_failure_keeps_partial_invalidation_and_propagates(
    setup, failed_step, error_cls
):
    error = error_cls("cache")
    calls = []

    async def delete(key):
        calls.append(key)
        if len(calls) == failed_step + 1:
            raise error

    api.cache.delete.side_effect = delete
    with pytest.raises(error_cls) as caught:
        await call(setup)
    assert caught.value is error
    assert (
        calls == ["practice:stats:3:*", "stats:*:3*", "review:*:3*"][: failed_step + 1]
    )
    assert [e[1][1] for e in setup.trace if e[0] == "snapshot"] == ["submit_before"]
    api.logger.warning.assert_not_called()


@pytest.mark.parametrize("boundary", ["debug", "submit_before", "submit_after"])
async def test_diagnostics_failure_stays_outside_service_error_mapping(
    setup, monkeypatch, boundary
):
    error = ValueError("diagnostic failure")

    def fail(*args):
        if boundary == "debug" or args[1] == boundary:
            raise error

    monkeypatch.setattr(
        api, "debug_log" if boundary == "debug" else "save_debug_snapshot", fail
    )
    with pytest.raises(ValueError) as caught:
        await call(setup)
    assert caught.value is error
    assert api.svc.batch_submit_answers.await_count == (
        1 if boundary == "submit_after" else 0
    )
    assert api.cache.delete.await_count == (3 if boundary == "submit_after" else 0)
    api.logger.warning.assert_not_called()


async def test_dependencies_are_read_after_await_at_original_use_sites(
    setup, monkeypatch
):
    after_cache = AsyncMock()
    after_snapshot = Mock()
    projection = Mock(return_value="projected")

    async def submit(**kwargs):
        setup.user.id = 12
        monkeypatch.setattr(api, "cache", SimpleNamespace(delete=after_cache))
        monkeypatch.setattr(api, "save_debug_snapshot", after_snapshot)
        monkeypatch.setattr(api, "BatchSubmitResponse", projection)
        return result()

    api.svc.batch_submit_answers.side_effect = submit
    assert await call(setup) == "projected"
    assert [c.args[0] for c in after_cache.await_args_list] == [
        "practice:stats:12:*",
        "stats:*:12*",
        "review:*:12*",
    ]
    after_snapshot.assert_called_once()
    assert projection.call_args.kwargs["trace_id"] == "context-trace"


async def test_cache_dependency_can_change_between_invalidations(setup, monkeypatch):
    replacement = AsyncMock()

    async def delete(key):
        monkeypatch.setattr(api, "cache", SimpleNamespace(delete=replacement))

    api.cache.delete.side_effect = delete
    await call(setup)
    assert [c.args[0] for c in replacement.await_args_list] == [
        "stats:*:3*",
        "review:*:3*",
    ]


async def test_legacy_direct_none_session_and_empty_answers_are_preserved(setup):
    data = request().model_copy(update={"session": None, "answers": []})
    await call(setup, data)
    kwargs = api.svc.batch_submit_answers.call_args.kwargs
    assert kwargs["session_meta"] is None and kwargs["answers"] == []


@pytest.mark.parametrize(
    "invalid", ["missing_count", "missing_results", "invalid_answer"]
)
async def test_result_validation_occurs_after_cache_invalidation(setup, invalid):
    payload = result()
    if invalid == "missing_count":
        del payload["total_correct"]
    elif invalid == "missing_results":
        del payload["results"]
    else:
        payload["results"] = [{}]
    api.svc.batch_submit_answers.side_effect = None
    api.svc.batch_submit_answers.return_value = payload
    with pytest.raises((KeyError, ValueError)):
        await call(setup)
    assert api.cache.delete.await_count == 3
    api.logger.warning.assert_not_called()
    snapshots = [e[1][1] for e in setup.trace if e[0] == "snapshot"]
    assert snapshots == (
        ["submit_before", "submit_after"]
        if invalid == "invalid_answer"
        else ["submit_before"]
    )


@pytest.mark.parametrize(
    "resolved,scope,status",
    [
        (None, (False, [2]), 404),
        (("ds", "DS"), (True, [2]), 400),
        (("ds", "DS"), (False, []), 400),
        (("ds", "DS"), (False, [2, 3]), 400),
        (("ds", "DS"), (False, [2]), 200),
    ],
)
async def test_retained_reset_validation_and_service_ownership(
    setup, monkeypatch, resolved, scope, status
):
    monkeypatch.setattr(
        api.svc, "resolve_subject_id_to_code", AsyncMock(return_value=resolved)
    )
    monkeypatch.setattr(
        api.svc, "resolve_practice_subject_scope", AsyncMock(return_value=scope)
    )
    reset = AsyncMock()
    monkeypatch.setattr(api.svc, "reset_sequential_progress", reset)
    kwargs = dict(
        data=SequentialPracticeResetRequest(subject_id=2),
        db=setup.db,
        current_user=setup.user,
    )
    if status != 200:
        with pytest.raises(HTTPException) as caught:
            await api.reset_sequential_practice(**kwargs)
        assert caught.value.status_code == status
        reset.assert_not_awaited()
    else:
        response = await api.reset_sequential_practice(**kwargs)
        assert response.subject_id == 2 and response.reset is True
        reset.assert_awaited_once_with(setup.db, user_id=3, subject_id=2)
    setup.db.commit.assert_not_awaited()


@pytest.mark.parametrize("found,scope", [(False, None), (True, None)])
async def test_retained_session_scope_distinguishes_missing_from_general(
    setup, monkeypatch, found, scope
):
    from app.services.practice import session_scope

    get_scope = AsyncMock(return_value=(found, scope))
    monkeypatch.setattr(session_scope, "get_practice_session_scope", get_scope)
    kwargs = dict(request_id="test-request", db=setup.db, current_user=setup.user)
    if found:
        response = await api.get_practice_session_scope_snapshot(**kwargs)
        assert response.scope is None and response.request_id == "test-request"
    else:
        with pytest.raises(HTTPException) as caught:
            await api.get_practice_session_scope_snapshot(**kwargs)
        assert caught.value.status_code == 404
    get_scope.assert_awaited_once_with(setup.db, user_id=3, request_id="test-request")


@pytest.mark.parametrize("status", [None, "processing", "ready", "unavailable"])
async def test_retained_session_summary_keeps_processing_and_missing_distinct(
    setup, monkeypatch, status
):
    from app.services.practice import knowledge_session_summary

    payload = (
        None if status is None else {"request_id": "test-request", "status": status}
    )
    get_summary = AsyncMock(return_value=payload)
    monkeypatch.setattr(
        knowledge_session_summary, "get_session_knowledge_summary", get_summary
    )
    kwargs = dict(request_id="test-request", db=setup.db, current_user=setup.user)
    if payload is None:
        with pytest.raises(HTTPException) as caught:
            await api.get_practice_session_knowledge_summary(**kwargs)
        assert caught.value.status_code == 404
    else:
        assert (
            await api.get_practice_session_knowledge_summary(**kwargs)
        ).status == status
    get_summary.assert_awaited_once_with(setup.db, user_id=3, request_id="test-request")
