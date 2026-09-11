from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.core.time_utils import utcnow
from app.models.admin import QuestionVersion, Subject
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.sequential_reservation import SequentialReservation
from app.models.user import User
from app.services import practice_service
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
async def test_batch_submit_releases_reservation_and_advances_records(tmp_path, monkeypatch):
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
            revision_map = {question.id: question.question_version_id for question in questions}
            batch_token, _, submission_request_id = practice_service.create_practice_batch_token(
                user_id=1,
                subject_id=2,
                mode="sequential",
                questions=questions,
                revision_ids=revision_map,
                sequential_reservation_request_id="submit-start",
                submission_request_id="submit-request",
            )
            revision_views = {question.question_version_id: question for question in questions}
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
            assert await db.scalar(
                select(SequentialReservation.question_id).where(
                    SequentialReservation.start_request_id == "submit-start"
                )
            ) is None
            assert (
                await db.scalar(
                    select(PracticeRecord.question_id).where(
                        PracticeRecord.user_id == 1,
                        PracticeRecord.question_id == issued_ids[0],
                    )
                )
                == issued_ids[0]
            )
            next_ids, _ = await _start(db, user_id=1, request_id="after-submit", count=2)
            assert next_ids == [3, 4]
    finally:
        await engine.dispose()


async def _async_value(value):
    return value
