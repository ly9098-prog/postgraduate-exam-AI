"""Real SQLite compatibility baseline for answer behavior recording and stats.

Exercises ``record_answer_behavior`` upsert semantics and ``get_behavior_stats``
accuracy/avg_time/by_subject aggregation against a real SQLite database.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all relationships before create_all
from app.core.database import Base
from app.models.admin import Subject
from app.models.answer_behavior import AnswerBehavior
from app.models.user import User
from app.services import behavior_service


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'behavior.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> tuple[int, int]:
    async with session_factory() as db:
        user = User(openid="behavior-openid", nickname="tester")
        db.add(user)
        await db.flush()
        subject = Subject(code="ds", name="数据结构", level=2, path="ds")
        db.add(subject)
        await db.flush()
        await db.commit()
        return user.id, subject.id


@pytest.mark.asyncio
async def test_record_creates_new_behavior(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    user_id, subject_id = await _seed(session_factory)

    async with session_factory() as db:
        result = await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            time_spent_sec=30, is_final_correct=True, subject_id=subject_id,
        )
        assert result.id is not None
        assert result.time_spent_sec == 30
        assert result.is_final_correct is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_record_updates_existing_with_same_practice_record(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    user_id, _ = await _seed(session_factory)

    async with session_factory() as db:
        first = await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            practice_record_id=100, time_spent_sec=20, is_final_correct=False,
        )
        second = await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            practice_record_id=100, time_spent_sec=45, is_final_correct=True,
        )
        assert first.id == second.id
        assert second.time_spent_sec == 45
        assert second.is_final_correct is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_record_without_practice_record_id_always_creates_new(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    user_id, _ = await _seed(session_factory)

    async with session_factory() as db:
        first = await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            time_spent_sec=10,
        )
        second = await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            time_spent_sec=20,
        )
        assert first.id != second.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_stats_empty_user_returns_zeros(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    user_id, _ = await _seed(session_factory)

    async with session_factory() as db:
        stats = await behavior_service.get_behavior_stats(db, user_id)
    assert stats["total_answers"] == 0
    assert stats["correct_count"] == 0
    assert stats["accuracy"] == 0
    assert stats["by_subject"] == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_stats_accuracy_and_avg_time(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    user_id, subject_id = await _seed(session_factory)

    async with session_factory() as db:
        await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            time_spent_sec=30, is_final_correct=True, subject_id=subject_id,
        )
        await behavior_service.record_answer_behavior(
            db, user_id, question_id=2, question_version_id=1,
            time_spent_sec=60, is_final_correct=False, subject_id=subject_id,
        )
        stats = await behavior_service.get_behavior_stats(db, user_id)

    assert stats["total_answers"] == 2
    assert stats["correct_count"] == 1
    assert stats["accuracy"] == 0.5
    assert stats["avg_time_sec"] == 45.0
    assert len(stats["by_subject"]) == 1
    assert stats["by_subject"][0]["subject_code"] == "ds"

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_stats_ignores_zero_time_in_avg(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    user_id, _ = await _seed(session_factory)

    async with session_factory() as db:
        await behavior_service.record_answer_behavior(
            db, user_id, question_id=1, question_version_id=1,
            time_spent_sec=0, is_final_correct=True,
        )
        await behavior_service.record_answer_behavior(
            db, user_id, question_id=2, question_version_id=1,
            time_spent_sec=40, is_final_correct=False,
        )
        stats = await behavior_service.get_behavior_stats(db, user_id)

    assert stats["total_answers"] == 2
    assert stats["avg_time_sec"] == 40.0

    await engine.dispose()
