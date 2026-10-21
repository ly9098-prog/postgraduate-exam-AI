from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.core.time_utils import utcnow
from app.models.admin import QuestionVersion, Subject
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.sequential_reservation import SequentialReservation
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.services import outbox_service, practice_service
from app.services.practice.sequential_service import (
    get_sequential_practice_questions,
)


async def _make_database(url: str):
    engine = create_async_engine(url, connect_args={"timeout": 30})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory, *, question_count: int = 8) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="seq-user-1"),
                User(id=2, openid="seq-user-2"),
                Subject(id=2, code="seq", name="Sequential", path="seq"),
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


async def _start(db, *, user_id: int, request_id: str, count: int = 2):
    questions, progress = await get_sequential_practice_questions(
        db,
        user_id=user_id,
        subject_id=2,
        subject_ids=[2],
        count=count,
        reservation_request_id=request_id,
    )
    return [int(question.id) for question in questions], progress


@pytest.mark.asyncio
async def test_sequential_reservations_progress_and_retry(tmp_path):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'sequential.db'}"
    )
    try:
        await _seed(session_factory, question_count=5)
        async with session_factory() as db:
            first, _ = await _start(db, user_id=1, request_id="first")
            await db.commit()
            second, _ = await _start(db, user_id=1, request_id="second")
            await db.commit()
            retry, _ = await _start(db, user_id=1, request_id="first")

        assert first == [1, 2]
        assert second == [3, 4]
        assert retry == first
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reservations_are_scoped_by_user_and_expire_or_rollback(tmp_path):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'sequential-scope.db'}"
    )
    try:
        await _seed(session_factory, question_count=3)
        async with session_factory() as db:
            user_one, _ = await _start(db, user_id=1, request_id="u1")
            await db.commit()
            user_two, _ = await _start(db, user_id=2, request_id="u2", count=1)
            await db.commit()
            assert user_one == [1, 2]
            assert user_two == [1]

            await db.execute(
                update(SequentialReservation).values(
                    expires_at=utcnow() - timedelta(seconds=1)
                )
            )
            await db.commit()
            expired_reused, _ = await _start(db, user_id=1, request_id="u1-retry")
            await db.commit()
            assert expired_reused == [1, 2]

            rolled_back, _ = await _start(db, user_id=1, request_id="rollback")
            await db.rollback()
            after_rollback, _ = await _start(db, user_id=1, request_id="rollback-retry")
            assert rolled_back == after_rollback == [3]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_starts_claim_disjoint_questions(tmp_path):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'sequential-concurrent.db'}"
    )
    try:
        await _seed(session_factory, question_count=10)

        async def start_concurrently(request_number: int) -> list[int]:
            for attempt in range(6):
                try:
                    async with session_factory() as db:
                        question_ids, _ = await _start(
                            db,
                            user_id=1,
                            request_id=f"concurrent-{request_number}",
                            count=1,
                        )
                        await db.commit()
                        return question_ids
                except OperationalError:
                    if attempt == 5:
                        raise
                    await asyncio.sleep(0.02 * (attempt + 1))
            raise AssertionError("unreachable")

        batches = await asyncio.gather(*(start_concurrently(i) for i in range(5)))
        claimed = [question_id for batch in batches for question_id in batch]
        assert len(claimed) == 5
        assert len(set(claimed)) == 5
        assert sorted(claimed) == list(range(1, 6))

        async with session_factory() as db:
            rows = await db.scalars(select(SequentialReservation.question_id))
            assert sorted(rows.all()) == list(range(1, 6))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_retry_of_same_request_reuses_batch(tmp_path):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'sequential-same-request.db'}"
    )
    try:
        await _seed(session_factory, question_count=4)

        async def retry_start() -> list[int]:
            for attempt in range(6):
                try:
                    async with session_factory() as db:
                        question_ids, _ = await _start(
                            db,
                            user_id=1,
                            request_id="same-request",
                            count=2,
                        )
                        await db.commit()
                        return question_ids
                except OperationalError:
                    if attempt == 5:
                        raise
                    await asyncio.sleep(0.02 * (attempt + 1))
            raise AssertionError("unreachable")

        first, second = await asyncio.gather(retry_start(), retry_start())
        assert first == second == [1, 2]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_batch_submit_releases_reservation_and_advances_records(
    tmp_path, monkeypatch
):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'sequential-submit.db'}"
    )
    try:
        await _seed(session_factory, question_count=4)
        async with session_factory() as db:
            issued_ids, _ = await _start(db, user_id=1, request_id="submit-start")
            await db.commit()
            questions = [
                SimpleNamespace(
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
                for question_id in issued_ids
            ]
            revision_map = {
                question.id: question.question_version_id for question in questions
            }
            batch_token, _, submission_request_id = (
                practice_service.create_practice_batch_token(
                    user_id=1,
                    subject_id=2,
                    mode="sequential",
                    questions=questions,
                    revision_ids=revision_map,
                    sequential_reservation_request_id="submit-start",
                    submission_request_id="submit-request",
                )
            )
            revision_views = {
                question.question_version_id: question for question in questions
            }
            monkeypatch.setattr(
                "app.services.question_revision_service.load_revision_views",
                lambda _db, _ids: _async_value(revision_views),
            )
            monkeypatch.setattr(
                "app.services.question_revision_service.load_revision_kp_names",
                lambda _db, _ids: _async_value({}),
            )
            monkeypatch.setattr(
                practice_service,
                "_create_answer_projection_outbox",
                lambda *_args, **_kwargs: _async_value(None),
            )
            now = utcnow()
            result = await practice_service.batch_submit_answers(
                db=db,
                user_id=1,
                answers=[
                    {
                        "question_id": question_id,
                        "user_answer": "A",
                        "used_time": 1,
                        "request_id": None,
                    }
                    for question_id in issued_ids
                ],
                session_meta={
                    "request_id": submission_request_id,
                    "subject_id": 2,
                    "mode": "sequential",
                    "started_at": now,
                    "finished_at": now,
                    "duration_sec": 2,
                    "question_count": len(issued_ids),
                    "answered_count": len(issued_ids),
                    "status": "completed",
                },
                skipped_question_ids=[],
                batch_token=batch_token,
            )
            assert result["total_correct"] == len(issued_ids)
            assert (
                await db.scalar(
                    select(SequentialReservation.question_id).where(
                        SequentialReservation.start_request_id == "submit-start"
                    )
                )
                is None
            )
            assert (
                await db.scalar(
                    select(PracticeRecord.question_id).where(
                        PracticeRecord.user_id == 1,
                        PracticeRecord.question_id == issued_ids[0],
                    )
                )
                == issued_ids[0]
            )
            next_ids, _ = await _start(
                db, user_id=1, request_id="after-submit", count=2
            )
            assert next_ids == [3, 4]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_batch_submit_recovers_stale_outbox_for_reused_record_id(
    tmp_path, monkeypatch
):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'practice-stale-outbox.db'}"
    )
    try:
        await _seed(session_factory, question_count=2)
        async with session_factory() as db:
            issued_ids, _ = await _start(db, user_id=1, request_id="stale-start")
            await db.commit()
            old_outbox_created_at = utcnow() - timedelta(days=1)
            questions = [
                SimpleNamespace(
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
                for question_id in issued_ids
            ]
            stale_record_id = 1
            db.add(
                TaskOutbox(
                    task_id=f"answer_projection:{stale_record_id}",
                    task_type="answer_projection",
                    payload={
                        "practice_record_id": stale_record_id,
                        "request_id": None,
                    },
                    schema_version=2,
                    status="pending",
                    created_at=old_outbox_created_at,
                )
            )
            await db.commit()

            async def _load_views(_db, _ids):
                return {
                    question.question_version_id: question for question in questions
                }

            async def _load_kps(_db, _ids):
                return {}

            monkeypatch.setattr(
                "app.services.question_revision_service.load_revision_views",
                _load_views,
            )
            monkeypatch.setattr(
                "app.services.question_revision_service.load_revision_kp_names",
                _load_kps,
            )

            result = await practice_service.batch_submit_answers(
                db=db,
                user_id=1,
                answers=[
                    {
                        "question_id": question_id,
                        "user_answer": "A",
                        "used_time": 1,
                        "request_id": None,
                    }
                    for question_id in issued_ids
                ],
                session_meta={
                    "request_id": "reused-record-id",
                    "subject_id": 2,
                    "mode": "sequential",
                    "started_at": utcnow(),
                    "finished_at": utcnow(),
                    "duration_sec": 2,
                    "question_count": len(issued_ids),
                    "answered_count": len(issued_ids),
                },
                skipped_question_ids=[],
                batch_token=(
                    practice_service.create_practice_batch_token(
                        user_id=1,
                        subject_id=2,
                        mode="sequential",
                        questions=questions,
                        revision_ids={
                            question.id: question.question_version_id
                            for question in questions
                        },
                        submission_request_id="reused-record-id",
                    )[0]
                ),
            )

            assert result["total_correct"] == len(issued_ids)
            records = (
                (
                    await db.execute(
                        select(PracticeRecord).where(PracticeRecord.user_id == 1)
                    )
                )
                .scalars()
                .all()
            )
            assert len(records) == len(issued_ids)
            tasks = (
                (
                    await db.execute(
                        select(TaskOutbox)
                        .where(TaskOutbox.task_id.like("answer_projection:%"))
                        .order_by(TaskOutbox.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert len(tasks) == len(issued_ids)
            recovered = {
                task.payload["practice_record_id"]: task
                for task in tasks
                if task.payload.get("recovered_from_orphan")
            }
            assert recovered
            assert any(
                task.status == "pending"
                and task.payload.get("practice_record_id")
                == task.payload["recovered_from_orphan"]["practice_record_id"]
                for task in recovered.values()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_source_with_pending_outbox_stays_fail_closed(
    tmp_path,
):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'practice-live-outbox.db'}"
    )
    try:
        await _seed(session_factory, question_count=1)
        async with session_factory() as db:
            record = PracticeRecord(
                user_id=1,
                question_id=1,
                question_version_id=1,
                subject_id=2,
                question_type="single_choice",
                user_answer="A",
                is_correct=True,
                answered_at=utcnow() - timedelta(days=1),
                mode="random",
                projection_state="pending",
            )
            db.add(record)
            await db.flush()
            db.add(
                TaskOutbox(
                    task_id=f"answer_projection:{record.id}",
                    task_type="answer_projection",
                    payload={
                        "practice_record_id": int(record.id),
                        "request_id": None,
                    },
                    schema_version=2,
                    status="pending",
                )
            )
            await db.commit()

            with pytest.raises(
                ValueError,
                match="Non-terminal outbox record exists",
            ):
                await outbox_service.create_outbox(
                    db,
                    task_id=f"answer_projection:{record.id}",
                    task_type="answer_projection",
                    payload={
                        "practice_record_id": int(record.id),
                        "request_id": None,
                    },
                    schema_version=2,
                )
            await db.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_batch_submit_replays_winner_after_claim_unique_race(
    tmp_path,
    monkeypatch,
):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'practice-claim-race.db'}"
    )
    try:
        await _seed(session_factory, question_count=1)
        now = utcnow()
        question = SimpleNamespace(
            id=1,
            question_id=1,
            question_version_id=1,
            subject_id=2,
            question_type="single_choice",
            answer="A",
            content={"text": "1"},
            options={"A": "A"},
            analysis=None,
            is_active=True,
        )
        batch_token, _, request_id = (
            practice_service.create_practice_batch_token(
                user_id=1,
                subject_id=2,
                mode="sequential",
                questions=[question],
                revision_ids={1: 1},
                submission_request_id="claim-race",
            )
        )
        session_meta = {
            "request_id": request_id,
            "subject_id": 2,
            "mode": "sequential",
            "started_at": now,
            "finished_at": now,
            "duration_sec": 2,
            "question_count": 1,
            "answered_count": 1,
        }
        payload_hash = practice_service._practice_submission_fingerprint(
            answers=[
                {
                    "question_id": 1,
                    "user_answer": "A",
                    "used_time": 1,
                    "request_id": None,
                }
            ],
            skipped_question_ids=[],
            session_meta=session_meta,
            batch_token=batch_token,
        )

        async def _load_views(_db, _ids):
            return {1: question}

        async def _load_kps(_db, _ids):
            return {}

        monkeypatch.setattr(
            "app.services.question_revision_service.load_revision_views",
            _load_views,
        )
        monkeypatch.setattr(
            "app.services.question_revision_service.load_revision_kp_names",
            _load_kps,
        )

        async with session_factory() as db:
            winner = PracticeSession(
                user_id=1,
                subject_id=2,
                request_id=request_id,
                mode="sequential",
                started_at=now,
                finished_at=now,
                duration_sec=2,
                question_count=1,
                answered_count=1,
                correct_count=1,
                wrong_count=0,
                status="completed",
                submission_payload_hash=payload_hash,
                submission_response={
                    "results": [{"question_id": 1, "status": "correct"}],
                    "total_correct": 1,
                    "total_wrong": 0,
                    "total_skipped": 0,
                },
            )
            db.add(winner)
            await db.commit()

            class _RaceSession:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            class _RaceTestDouble:
                def __init__(self, session):
                    self.session = session
                    self.lookups = 0

                def get_bind(self):
                    return self.session.get_bind()

                async def execute(self, statement, *args, **kwargs):
                    return await self.session.execute(statement, *args, **kwargs)

                async def scalar(self, statement, *args, **kwargs):
                    self.lookups += 1
                    if self.lookups == 1:
                        return None
                    with self.session.no_autoflush:
                        return await self.session.scalar(statement, *args, **kwargs)

                def begin_nested(self):
                    return _RaceSession()

                def add(self, obj):
                    self.session.add(obj)

                async def flush(self):
                    raise IntegrityError(
                        "INSERT practice_sessions",
                        {},
                        RuntimeError(
                            "UNIQUE constraint failed: "
                            "practice_sessions.user_id, "
                            "practice_sessions.request_id"
                        ),
                    )

            race_db = _RaceTestDouble(db)

            result = await practice_service.batch_submit_answers(
                db=race_db,
                user_id=1,
                answers=[
                    {
                        "question_id": 1,
                        "user_answer": "A",
                        "used_time": 1,
                        "request_id": None,
                    }
                ],
                session_meta=session_meta,
                skipped_question_ids=[],
                batch_token=batch_token,
            )
            assert result["total_correct"] == 1
            assert result["results"] == [{"question_id": 1, "status": "correct"}]
            assert race_db.lookups == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_batch_submit_rolls_back_session_and_records_when_outbox_fails(
    tmp_path, monkeypatch
):
    engine, session_factory = await _make_database(
        f"sqlite+aiosqlite:///{tmp_path / 'practice-atomic-failure.db'}"
    )
    try:
        await _seed(session_factory, question_count=2)
        async with session_factory() as db:
            issued_ids, _ = await _start(db, user_id=1, request_id="atomic-start")
            await db.commit()
            questions = [
                SimpleNamespace(
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
                for question_id in issued_ids
            ]
            batch_token, _, submission_request_id = (
                practice_service.create_practice_batch_token(
                    user_id=1,
                    subject_id=2,
                    mode="sequential",
                    questions=questions,
                    revision_ids={
                        question.id: question.question_version_id
                        for question in questions
                    },
                    submission_request_id="atomic-submit",
                )
            )

            async def _load_views(_db, _ids):
                return {
                    question.question_version_id: question for question in questions
                }

            async def _load_kps(_db, _ids):
                return {}

            monkeypatch.setattr(
                "app.services.question_revision_service.load_revision_views",
                _load_views,
            )
            monkeypatch.setattr(
                "app.services.question_revision_service.load_revision_kp_names",
                _load_kps,
            )

            async def _fail_outbox(*_args, **_kwargs):
                raise RuntimeError("simulated outbox failure")

            monkeypatch.setattr(
                practice_service,
                "_create_answer_projection_outbox",
                _fail_outbox,
            )
            now = utcnow()
            with pytest.raises(RuntimeError, match="simulated outbox failure"):
                await practice_service.batch_submit_answers(
                    db=db,
                    user_id=1,
                    answers=[
                        {
                            "question_id": question_id,
                            "user_answer": "A",
                            "used_time": 1,
                            "request_id": None,
                        }
                        for question_id in issued_ids
                    ],
                    session_meta={
                        "request_id": submission_request_id,
                        "subject_id": 2,
                        "mode": "sequential",
                        "started_at": now,
                        "finished_at": now,
                        "duration_sec": 2,
                        "question_count": len(issued_ids),
                        "answered_count": len(issued_ids),
                    },
                    skipped_question_ids=[],
                    batch_token=batch_token,
                )
            await db.rollback()

        async with session_factory() as verify_db:
            session_rows = (
                (
                    await verify_db.execute(
                        select(PracticeSession).where(
                            PracticeSession.user_id == 1,
                            PracticeSession.request_id == submission_request_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            record_rows = (
                (
                    await verify_db.execute(
                        select(PracticeRecord).where(PracticeRecord.user_id == 1)
                    )
                )
                .scalars()
                .all()
            )
            assert session_rows == []
            assert record_rows == []
    finally:
        await engine.dispose()


async def _async_value(value):
    return value
