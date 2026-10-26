"""Characterize answer projection ownership, side-effect order and failure scope."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.practice import answer_projection_service as service


@pytest.fixture
def projection(monkeypatch):
    from app.services import (
        adaptive_learning_service,
        behavior_service,
        mastery_service,
        question_review_service,
        recommendation_log_service,
        vector_retrieval_service,
    )

    record = service._ProjectionSource(
        id=11,
        user_id=12,
        question_id=13,
        question_version_id=14,
        subject_id=15,
        user_answer=" A ",
        is_correct=False,
        used_time=0,
        answered_at=datetime(2026, 10, 26),
        mode="",
        projection_state="pending",
    )
    revision = service._RevisionSource(id=14, question_id=13, subject_id=0, answer="B")
    state = SimpleNamespace(
        record=record,
        revision=revision,
        current=14,
        events=[],
        calls={},
        failures={},
        mastery={"mastery_after": 21, "mastery_delta": -2},
        transition=SimpleNamespace(is_due_review=True, is_overdue_review=False),
    )

    def port(name, result=None):
        async def invoke(*args, **kwargs):
            state.events.append(name)
            state.calls[name] = (args, kwargs)
            if name in state.failures:
                raise state.failures[name]
            return result() if callable(result) else result

        return invoke

    for name, result in (
        ("_verify_projection_schema_contract", None),
        ("_lock_projection_source", lambda: state.record),
        ("_load_revision_source", lambda: state.revision),
        ("_load_current_question_version", lambda: state.current),
        ("_finish_projection", None),
    ):
        monkeypatch.setattr(service, name, port(name, result))
    for module, name, result in (
        (behavior_service, "record_answer_behavior", None),
        (
            mastery_service,
            "update_user_knowledge_state_after_answer",
            lambda: state.mastery,
        ),
        (recommendation_log_service, "mark_recommendation_answered", None),
        (
            question_review_service,
            "update_user_question_state_after_answer",
            lambda: state.transition,
        ),
        (adaptive_learning_service, "update_adaptive_state_after_answer", None),
        (vector_retrieval_service, "invalidate_vector_cache", None),
    ):
        monkeypatch.setattr(module, name, port(name, result))
    state.db = SimpleNamespace(commit=port("commit"), rollback=port("rollback"))
    state.logger = Mock()
    monkeypatch.setattr(service, "logger", state.logger)
    return state


STAGES = [
    "_verify_projection_schema_contract",
    "_lock_projection_source",
    "_load_revision_source",
    "_load_current_question_version",
    "record_answer_behavior",
    "update_user_knowledge_state_after_answer",
    "mark_recommendation_answered",
    "update_user_question_state_after_answer",
    "update_adaptive_state_after_answer",
    "_finish_projection",
    "commit",
    "invalidate_vector_cache",
]


async def run(state):
    return await service.project_practice_answer(
        state.db,
        practice_record_id=11,
        request_id="request",
    )


@pytest.mark.asyncio
async def test_current_revision_preserves_ports_payload_and_commit_order(projection):
    state = projection
    assert await run(state) == {
        "processed": True,
        "duplicate": False,
        "projection_state": "completed",
        "question_version_id": 14,
    }
    assert state.events == STAGES
    assert state.calls["record_answer_behavior"] == (
        (),
        {
            "db": state.db,
            "user_id": 12,
            "question_id": 13,
            "practice_record_id": 11,
            "question_version_id": 14,
            "time_spent_sec": 0,
            "is_first_correct": False,
            "is_final_correct": False,
            "user_answer": "A",
            "correct_answer": "B",
            "subject_id": 15,
            "session_type": "practice",
            "commit": False,
        },
    )
    assert state.calls["update_user_knowledge_state_after_answer"] == (
        (state.db, 12, 13, False),
        {"used_time": 0, "question_version_id": 14},
    )
    assert state.calls["mark_recommendation_answered"] == (
        (state.db, 12, 13, False),
        {"request_id": "request", "mastery_after": 21, "mastery_delta": -2},
    )
    assert state.calls["update_user_question_state_after_answer"] == (
        (state.db, 12, 13, False),
        {"used_time": 0, "answered_at": state.record.answered_at},
    )
    assert state.calls["update_adaptive_state_after_answer"] == (
        (state.db,),
        {
            "user_id": 12,
            "question_id": 13,
            "is_correct": False,
            "answer_time_seconds": 0,
            "answered_at": state.record.answered_at,
            "is_due_review": True,
            "is_overdue_review": False,
        },
    )
    assert state.calls["_finish_projection"] == (
        (state.db,),
        {"practice_record_id": 11, "target_state": "completed"},
    )
    assert state.calls["invalidate_vector_cache"] == ((12,), {})
    state.logger.debug.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [None, 99])
async def test_old_revision_preserves_evidence_but_skips_mutable_state(
    projection, current
):
    projection.current = current
    result = await run(projection)
    assert result["projection_state"] == "revision_only"
    assert projection.events == STAGES[:7] + STAGES[9:]
    assert projection.calls["_finish_projection"][1]["target_state"] == "revision_only"


@pytest.mark.asyncio
async def test_missing_record_warns_and_terminal_receipt_short_circuits(projection):
    state = projection
    state.record = None
    assert await run(state) == {"processed": False, "missing": True}
    assert state.events == STAGES[:2]
    state.logger.warning.assert_called_once_with(
        "answer projection record missing: record_id=%s",
        11,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", ["completed", "revision_only", "unexpected"])
async def test_nonpending_receipt_has_no_projection_or_transaction_work(
    projection, receipt
):
    from dataclasses import replace

    projection.record = replace(projection.record, projection_state=receipt)
    assert await run(projection) == {
        "processed": False,
        "duplicate": True,
        "projection_state": receipt,
    }
    assert projection.events == STAGES[:2]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["no-version", "missing", "mismatch"])
async def test_invalid_revision_raises_before_current_question_lookup(
    projection, invalid
):
    from dataclasses import replace

    if invalid == "no-version":
        projection.record = replace(projection.record, question_version_id=None)
        message = "practice record 11 has no question_version_id"
    else:
        projection.revision = (
            None
            if invalid == "missing"
            else replace(projection.revision, question_id=99)
        )
        message = "practice record 11 references invalid question revision"
    with pytest.raises(RuntimeError, match=message):
        await run(projection)
    assert projection.events == STAGES[: 2 if invalid == "no-version" else 3]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("cancel", [False, True])
async def test_stage_failure_preserves_exception_and_transaction_boundary(
    projection, stage, cancel
):
    error = asyncio.CancelledError("cancel") if cancel else RuntimeError("failure")
    projection.failures[stage] = error
    if stage == "invalidate_vector_cache" and not cancel:
        assert (await run(projection))["processed"] is True
        projection.logger.debug.assert_called_once_with(
            "vector cache invalidation failed uid=%d",
            12,
            exc_info=True,
        )
    else:
        with pytest.raises(type(error)) as caught:
            await run(projection)
        assert caught.value is error
    assert projection.events == STAGES[: STAGES.index(stage) + 1]
    assert "rollback" not in projection.events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mastery", [None, {}, {"mastery_after": 0, "mastery_delta": 0}]
)
async def test_empty_and_zero_mastery_values_are_forwarded(projection, mastery):
    projection.mastery = mastery
    await run(projection)
    kwargs = projection.calls["mark_recommendation_answered"][1]
    assert kwargs["mastery_after"] == (mastery or {}).get("mastery_after")
    assert kwargs["mastery_delta"] == (mastery or {}).get("mastery_delta")
