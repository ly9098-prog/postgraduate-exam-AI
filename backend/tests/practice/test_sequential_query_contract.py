"""Characterize issuance ports, SQL order, answerable revisions and progress."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select, update

from app.models.admin import QuestionVersion
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.sequential_reservation import SequentialReservation
from app.services.practice import sequential_service as service
from tests.practice.test_sequential_reservation_contract import ScriptedDB, compiled
from tests.test_services.test_sequential_reservation import _make_database, _seed

NOW = datetime(2026, 10, 26, 12)


@pytest.fixture
def ports(monkeypatch):
    events = []
    reset = AsyncMock(side_effect=lambda *args, **kwargs: events.append("reset") or NOW)
    answered = Mock(wraps=service._answered_ids_query)
    reserve = AsyncMock(return_value=[4, 99, 3])
    clock = Mock(side_effect=lambda: events.append("clock") or NOW)
    uuid = Mock(return_value=SimpleNamespace(hex="fixed"))
    scope = Mock(wraps=service._sequential_scope_key)
    log = Mock()
    for name, value in {
        "_get_reset_at": reset,
        "_answered_ids_query": answered,
        "_reserve_sequential_questions": reserve,
        "utcnow": clock,
        "uuid4": uuid,
        "_sequential_scope_key": scope,
        "logger": log,
    }.items():
        monkeypatch.setattr(service, name, value)
    return SimpleNamespace(
        events=events,
        reset=reset,
        answered=answered,
        reserve=reserve,
        clock=clock,
        uuid=uuid,
        scope=scope,
        log=log,
    )


async def issue(db, **kwargs):
    return await service.get_sequential_practice_questions(
        db,
        user_id=11,
        subject_id=7,
        subject_ids=[7],
        **kwargs,
    )


@pytest.mark.asyncio
async def test_public_entry_preserves_filter_ports_counts_reservation_and_hydration(
    ports, monkeypatch
):
    questions = [SimpleNamespace(id=3), SimpleNamespace(id=4)]
    db = ScriptedDB([questions], scalars=[5, 2])
    names = ["scope"]
    kp_condition = Question.id > 1
    kp = Mock(return_value=[kp_condition])
    revision = Mock(wraps=service.latest_question_revision_scope_condition)
    monkeypatch.setattr(service, "kp_exact_conditions", kp)
    monkeypatch.setattr(service, "latest_question_revision_scope_condition", revision)
    rows, progress = await issue(
        db, knowledge_points=names, reservation_request_id=" request "
    )
    assert rows == [questions[1], questions[0]]
    assert progress == {
        "subject_id": 7,
        "total_questions": 5,
        "completed_questions": 2,
        "remaining_questions": 3,
        "cycle_completed": False,
        "next_question_id": 4,
    }
    revision.assert_called_once_with([7], service.SEQUENTIAL_ANSWERABLE_QUESTION_TYPES)
    kp.assert_called_once_with(names)
    ports.scope.assert_called_once_with(names)
    ports.reset.assert_awaited_once_with(db, user_id=11, subject_id=7)
    ports.answered.assert_called_once_with(user_id=11, subject_id=7, reset_at=NOW)
    args = ports.reserve.await_args.kwargs
    assert args["conditions"][-1] is kp_condition
    assert args["start_request_id"] == "request" and args["now"] is NOW
    assert args["count"] == 20
    assert ports.events == ["reset", "clock"]
    ports.uuid.assert_not_called()
    assert [event for event, _ in db.events] == ["scalar", "scalar", "execute"]
    total_sql, _ = compiled(db.events[0][1])
    completed_sql, _ = compiled(db.events[1][1])
    load_sql, _ = compiled(db.events[2][1])
    assert "count(questions.id)" in total_sql
    assert "practice_records" not in total_sql and "practice_records" in completed_sql
    assert load_sql.endswith("ORDER BY questions.id ASC")
    assert len(db.events[2][1]._with_options) == 1
    ports.log.info.assert_called_once_with(
        "[Sequential Query] uid=%d subject_id=%d total=%d completed=%d remaining=%d returned=%d",
        11,
        7,
        5,
        2,
        3,
        2,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("total", "completed", "remaining", "done"),
    [
        (None, None, 0, False),
        (3, 3, 0, True),
        (3, 5, 0, True),
        (5, 2, 3, False),
    ],
)
async def test_empty_reservation_skips_hydration_and_retains_bank_progress(
    ports,
    total,
    completed,
    remaining,
    done,
):
    ports.reserve.return_value = []
    db = ScriptedDB([], scalars=[total, completed])
    rows, progress = await issue(db)
    assert rows == [] and progress["next_question_id"] is None
    assert progress["remaining_questions"] == remaining
    assert progress["cycle_completed"] is done
    assert [event for event, _ in db.events] == ["scalar", "scalar"]
    assert ports.reserve.await_args.kwargs["start_request_id"] == "seqstart:11:fixed"


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_ids", [[], [7, 8], [8]])
async def test_subject_validation_precedes_all_ports(ports, subject_ids):
    with pytest.raises(ValueError, match="单一具体科目"):
        await service.get_sequential_practice_questions(
            object(),
            user_id=11,
            subject_id=7,
            subject_ids=subject_ids,
        )
    ports.reset.assert_not_awaited()
    ports.clock.assert_not_called()
    ports.reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [" ", "x" * 129])
async def test_request_validation_follows_reset_query_but_precedes_clock_and_counts(
    ports, request_id
):
    db = ScriptedDB([])
    with pytest.raises(ValueError, match="start_request_id"):
        await issue(db, reservation_request_id=request_id)
    ports.reset.assert_awaited_once()
    ports.answered.assert_called_once()
    ports.clock.assert_not_called()
    ports.scope.assert_not_called()
    ports.reserve.assert_not_awaited()
    assert not db.events


@pytest.mark.asyncio
async def test_real_sqlite_filters_latest_unanswerable_revisions_and_reset_cutoff(
    tmp_path,
):
    engine, factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}"
    )
    try:
        await _seed(factory, question_count=5)
        async with factory() as db:
            await db.execute(
                update(Question).where(Question.id == 2).values(question_type="essay")
            )
            await db.execute(
                update(QuestionVersion)
                .where(QuestionVersion.id == 2)
                .values(
                    question_type="essay",
                )
            )
            db.add(
                QuestionVersion(
                    question_id=3,
                    version=2,
                    subject_id=2,
                    question_type="essay",
                    content={},
                    answer="x",
                    difficulty=3,
                    is_active=True,
                )
            )
            db.add(
                PracticeSession(
                    user_id=1,
                    subject_id=2,
                    request_id="reset",
                    mode="sequential_reset",
                    status="marker",
                    started_at=NOW,
                    finished_at=NOW,
                    duration_sec=0,
                )
            )
            for qid, answered_at, mode in [
                (1, NOW, "sequential"),
                (4, NOW + timedelta(seconds=1), "sequential"),
                (5, NOW + timedelta(seconds=1), "random"),
            ]:
                db.add(
                    PracticeRecord(
                        user_id=1,
                        subject_id=2,
                        question_id=qid,
                        question_version_id=qid,
                        question_type="single_choice",
                        user_answer="A",
                        is_correct=True,
                        answered_at=answered_at,
                        mode=mode,
                    )
                )
            await db.commit()
            rows, progress = await service.get_sequential_practice_questions(
                db,
                user_id=1,
                subject_id=2,
                subject_ids=[2],
                reservation_request_id="scope",
            )
            assert [row.id for row in rows] == [1, 5]
            assert progress["total_questions"] == 3
            assert progress["completed_questions"] == 1
            assert progress["remaining_questions"] == 2
            await db.rollback()
        async with factory() as db:
            assert await db.scalar(select(SequentialReservation.id)) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_count_failure_propagates_before_reservation_or_success_log(
    ports, stage, error_type
):
    error = error_type("count failed")
    values = [5, 2]
    values[stage] = error
    db = ScriptedDB([], scalars=values)
    with pytest.raises(error_type) as caught:
        await issue(db)
    assert caught.value is error
    ports.reserve.assert_not_awaited()
    ports.log.info.assert_not_called()
    assert [event for event, _ in db.events] == ["scalar"] * (stage + 1)
