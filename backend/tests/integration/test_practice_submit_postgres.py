"""Real PostgreSQL coverage for practice submission atomicity.

Run only against the server-side test database:

    PRACTICE_TEST_POSTGRES_URL=postgresql+asyncpg://... \
      python -m pytest tests/integration/test_practice_submit_postgres.py \
      --run-integration -v

The module creates its own schema and never touches the production ``public``
schema.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register relationships before create_all
from app.core.database import Base
from app.core.time_utils import utcnow
from app.models.admin import QuestionVersion, Subject
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.services import practice_service

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

POSTGRES_URL = os.environ.get("PRACTICE_TEST_POSTGRES_URL", "")
if not POSTGRES_URL:
    pytest.skip(
        "set PRACTICE_TEST_POSTGRES_URL to run real PostgreSQL practice tests",
        allow_module_level=True,
    )


TEST_SCHEMA = "practice_submit_test"


async def _seed(factory, *, question_count: int) -> None:
    await _clear_schema(factory)
    async with factory() as db:
        db.add_all(
            [
                User(id=1, openid="pg-practice-user-1"),
                User(id=2, openid="pg-practice-user-2"),
                Subject(id=2, code="pg-seq", name="PG Sequential", path="pg-seq"),
            ]
        )
        await db.flush()
        for question_id in range(1, question_count + 1):
            db.add(
                Question(
                    id=question_id,
                    subject_id=2,
                    question_type="single_choice",
                    content={"text": str(question_id)},
                    options={"A": "A"},
                    answer="A",
                    review_status="approved",
                    is_active=True,
                )
            )
            await db.flush()
            db.add(
                QuestionVersion(
                    id=question_id,
                    question_id=question_id,
                    version=1,
                    subject_id=2,
                    question_type="single_choice",
                    content={"text": str(question_id)},
                    options={"A": "A"},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                )
            )
        await db.commit()


async def _clear_schema(factory) -> None:
    async with factory() as db:
        for table in reversed(Base.metadata.sorted_tables):
            if table.schema is None:
                await db.execute(
                    text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE')
                )
        await db.commit()


def _question_view(question_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=question_id,
        question_id=question_id,
        question_version_id=question_id,
        subject_id=2,
        question_type="single_choice",
        answer="A",
        content={"text": str(question_id)},
        options={"A": "A"},
        analysis=None,
        is_active=True,
    )


def _submission(
    *,
    request_id: str,
    question_ids: list[int],
    duration_sec: int | None = None,
) -> tuple[list[SimpleNamespace], dict, list[dict], str]:
    questions = [_question_view(question_id) for question_id in question_ids]
    batch_token, _, signed_request_id = practice_service.create_practice_batch_token(
        user_id=1,
        subject_id=2,
        mode="sequential",
        questions=questions,
        revision_ids={
            question.id: question.question_version_id for question in questions
        },
        submission_request_id=request_id,
    )
    finished_at = utcnow()
    if duration_sec is None:
        duration_sec = len(question_ids) + 1
    started_at = finished_at - timedelta(seconds=duration_sec)
    session_meta = {
        "request_id": signed_request_id,
        "subject_id": 2,
        "mode": "sequential",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
        "question_count": len(question_ids),
        "answered_count": len(question_ids),
    }
    answers = [
        {
            "question_id": question_id,
            "user_answer": "A",
            "used_time": 1,
            "request_id": None,
        }
        for question_id in question_ids
    ]
    return questions, session_meta, answers, batch_token


async def _database_context():
    engine = create_async_engine(
        POSTGRES_URL,
        echo=False,
        connect_args={
            "timeout": 30,
            "server_settings": {"search_path": TEST_SCHEMA},
        },
    )
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
        await connection.execute(text(f'CREATE SCHEMA "{TEST_SCHEMA}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{TEST_SCHEMA}"'))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _teardown_database(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
    await engine.dispose()


def _run_case(case):
    async def _wrapped():
        engine, factory = await _database_context()
        try:
            await case(factory)
        finally:
            await _teardown_database(engine)

    asyncio.run(_wrapped())


async def _submit(
    factory,
    *,
    question_ids: list[int],
    request_id: str,
    answer_override: str | None = None,
    monkeypatch=None,
    fail_outbox: bool = False,
    duration_sec: int | None = None,
    materialize_outbox: bool = True,
):
    questions, session_meta, answers, batch_token = _submission(
        request_id=request_id,
        question_ids=question_ids,
        duration_sec=duration_sec,
    )
    if answer_override is not None:
        answers[0]["user_answer"] = answer_override
    if monkeypatch is not None:
        monkeypatch.setattr(
            "app.services.question_revision_service.load_revision_views",
            lambda _db, _ids: _async_value(
                {question.question_version_id: question for question in questions}
            ),
        )
        monkeypatch.setattr(
            "app.services.question_revision_service.load_revision_kp_names",
            lambda _db, _ids: _async_value({}),
        )
        if fail_outbox:

            async def _fail_outbox(*_args, **_kwargs):
                raise RuntimeError("simulated postgres outbox failure")

            monkeypatch.setattr(
                practice_service,
                "_create_answer_projection_outbox",
                _fail_outbox,
            )
        if not materialize_outbox:
            original = practice_service._create_answer_projection_outbox
            monkeypatch.setattr(
                practice_service,
                "_create_answer_projection_outbox",
                lambda *_args, **_kwargs: _async_value(None),
            )
            try:
                async with factory() as db:
                    return await practice_service.batch_submit_answers(
                        db=db,
                        user_id=1,
                        answers=answers,
                        session_meta=session_meta,
                        skipped_question_ids=[],
                        batch_token=batch_token,
                    )
            finally:
                monkeypatch.setattr(
                    practice_service,
                    "_create_answer_projection_outbox",
                    original,
                )
    async with factory() as db:
        return await practice_service.batch_submit_answers(
            db=db,
            user_id=1,
            answers=answers,
            session_meta=session_meta,
            skipped_question_ids=[],
            batch_token=batch_token,
        )


async def _submit_from_payload(
    factory,
    *,
    session_meta: dict,
    answers: list[dict],
    batch_token: str,
    monkeypatch,
    materialize_outbox: bool,
):
    original = practice_service._create_answer_projection_outbox
    if not materialize_outbox:
        monkeypatch.setattr(
            practice_service,
            "_create_answer_projection_outbox",
            lambda *_args, **_kwargs: _async_value(None),
        )
    try:
        async with factory() as db:
            return await practice_service.batch_submit_answers(
                db=db,
                user_id=1,
                answers=answers,
                session_meta=session_meta,
                skipped_question_ids=[],
                batch_token=batch_token,
            )
    finally:
        if not materialize_outbox:
            monkeypatch.setattr(
                practice_service,
                "_create_answer_projection_outbox",
                original,
            )


async def _async_value(value):
    return value


async def _count_rows(factory) -> dict[str, int]:
    async with factory() as db:
        sessions = await db.scalar(select(func.count(PracticeSession.id)))
        records = await db.scalar(select(func.count(PracticeRecord.id)))
        outbox = await db.scalar(select(func.count(TaskOutbox.id)))
    return {
        "sessions": int(sessions or 0),
        "records": int(records or 0),
        "outbox": int(outbox or 0),
    }


def test_concurrent_same_request_has_one_winner(monkeypatch):
    async def _case(factory):
        await _seed(factory, question_count=2)
        request_id = f"pg-same-{uuid.uuid4().hex}"
        _, session_meta, answers, batch_token = _submission(
            request_id=request_id,
            question_ids=[1, 2],
        )

        async def submit_once():
            return await _submit_from_payload(
                factory,
                session_meta=session_meta,
                answers=answers,
                batch_token=batch_token,
                monkeypatch=monkeypatch,
                materialize_outbox=False,
            )

        results = await asyncio.gather(submit_once(), submit_once())
        assert all(result["total_correct"] == 2 for result in results)
        assert results[0] == results[1]
        counts = await _count_rows(factory)
        assert counts["sessions"] == 1
        assert counts["records"] == 2

    _run_case(_case)


def test_concurrent_same_request_with_different_payload_conflicts(monkeypatch):
    async def _case(factory):
        await _seed(factory, question_count=1)
        request_id = f"pg-conflict-{uuid.uuid4().hex}"
        _, session_meta, answers, batch_token = _submission(
            request_id=request_id,
            question_ids=[1],
        )
        correct_answers = [dict(answers[0], user_answer="B")]
        wrong_answers = [dict(answers[0], user_answer="C")]

        async def submit_correct():
            return await _submit_from_payload(
                factory,
                session_meta=session_meta,
                answers=correct_answers,
                batch_token=batch_token,
                monkeypatch=monkeypatch,
                materialize_outbox=False,
            )

        async def submit_wrong():
            return await _submit_from_payload(
                factory,
                session_meta=session_meta,
                answers=wrong_answers,
                batch_token=batch_token,
                monkeypatch=monkeypatch,
                materialize_outbox=False,
            )

        results = await asyncio.gather(
            submit_correct(), submit_wrong(), return_exceptions=True
        )
        successes = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, BaseException)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], practice_service.PracticeSubmissionConflictError)
        counts = await _count_rows(factory)
        assert counts["sessions"] == 1
        assert counts["records"] == 1

    _run_case(_case)


def test_outbox_failure_rolls_back_all_rows(monkeypatch):
    async def _case(factory):
        await _seed(factory, question_count=2)
        request_id = f"pg-rollback-{uuid.uuid4().hex}"
        original = practice_service._create_answer_projection_outbox

        async def _fail_outbox(*_args, **_kwargs):
            raise RuntimeError("simulated postgres outbox failure")

        monkeypatch.setattr(
            practice_service,
            "_create_answer_projection_outbox",
            _fail_outbox,
        )
        with pytest.raises(RuntimeError, match="simulated postgres outbox failure"):
            await _submit(
                factory,
                question_ids=[1, 2],
                request_id=request_id,
                monkeypatch=monkeypatch,
            )
        monkeypatch.setattr(
            practice_service,
            "_create_answer_projection_outbox",
            original,
        )
        assert await _count_rows(factory) == {
            "sessions": 0,
            "records": 0,
            "outbox": 0,
        }

        result = await _submit(
            factory,
            question_ids=[1, 2],
            request_id=request_id,
            monkeypatch=monkeypatch,
        )
        assert result["total_correct"] == 2
        assert await _count_rows(factory) == {
            "sessions": 1,
            "records": 2,
            "outbox": 2,
        }

    _run_case(_case)


def test_stale_outbox_rebinds_and_live_source_fails_closed(monkeypatch):
    async def _case(factory):
        await _seed(factory, question_count=1)
        async with factory() as db:
            stale = TaskOutbox(
                task_id="answer_projection:1",
                task_type="answer_projection",
                payload={"practice_record_id": 1, "request_id": None},
                schema_version=2,
                status="pending",
                created_at=utcnow() - timedelta(days=1),
                updated_at=utcnow() - timedelta(days=1),
            )
            db.add(stale)
            await db.flush()
            await db.execute(
                text(
                    "UPDATE task_outbox "
                    "SET created_at = :created_at, updated_at = :updated_at "
                    "WHERE task_id = :task_id "
                ),
                {
                    "created_at": utcnow() - timedelta(days=1),
                    "updated_at": utcnow() - timedelta(days=1),
                    "task_id": "answer_projection:1",
                },
            )
            await db.commit()

        result = await _submit(
            factory,
            question_ids=[1],
            request_id=f"pg-stale-{uuid.uuid4().hex}",
            monkeypatch=monkeypatch,
        )
        assert result["total_correct"] == 1
        async with factory() as db:
            row = await db.scalar(
                select(TaskOutbox).where(TaskOutbox.task_id == "answer_projection:1")
            )
            assert row is not None
            assert row.payload["recovered_from_orphan"]["practice_record_id"] == 1
            assert row.status == "pending"

            live_record = await db.scalar(select(PracticeRecord).limit(1))
            assert live_record is not None
            old_time = utcnow() - timedelta(days=2)
            await db.execute(
                text(
                    "UPDATE practice_records SET created_at = :created_at "
                    "WHERE id = :id"
                ),
                {"created_at": old_time, "id": live_record.id},
            )
            await db.execute(
                text(
                    "UPDATE task_outbox SET created_at = :created_at "
                    "WHERE task_id = :task_id"
                ),
                {"created_at": utcnow(), "task_id": row.task_id},
            )
            await db.refresh(row)
            with pytest.raises(ValueError, match="Non-terminal outbox record exists"):
                from app.services import outbox_service

                await outbox_service.create_outbox(
                    db,
                    task_id=row.task_id,
                    task_type="answer_projection",
                    payload={"practice_record_id": live_record.id, "request_id": None},
                    schema_version=2,
                )
            await db.rollback()

    _run_case(_case)
