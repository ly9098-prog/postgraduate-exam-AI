"""Real SQLite compatibility baseline for wrong question recording and stats."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.models.user import User
from app.services import wrong_question_service


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'wq.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory):
    async with session_factory() as db:
        user = User(openid="wq-openid", nickname="tester")
        db.add(user)
        await db.flush()
        subject = Subject(code="ds", name="DS", level=2, path="ds")
        db.add(subject)
        await db.flush()
        question = Question(
            subject_id=subject.id, question_type="single_choice",
            content={"stem": "test"}, options={"A": {"label": "A", "text": "a"}},
            answer="A", review_status="approved", is_active=True,
        )
        db.add(question)
        await db.flush()
        version = QuestionVersion(
            question_id=question.id, version=1, question_type="single_choice",
            content={"stem": "test"}, options={"A": {"label": "A", "text": "a"}},
            answer="A", difficulty=3, is_active=True, change_source="system",
        )
        db.add(version)
        await db.flush()
        question.current_version_id = version.id
        await db.commit()
        return user.id, question.id, version.id


@pytest.mark.asyncio
async def test_record_creates_new_wrong_question(tmp_path):
    engine, sf = await _make_database(tmp_path)
    uid, qid, vid = await _seed(sf)
    async with sf() as db:
        wq = await wrong_question_service.record_wrong(
            db, uid, qid, wrong_answer="B", question_version_id=vid)
        assert wq.id is not None
        assert wq.wrong_answer == "B"
        assert wq.review_count == 1
        assert wq.is_active is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_increments_review_count_on_repeat(tmp_path):
    engine, sf = await _make_database(tmp_path)
    uid, qid, vid = await _seed(sf)
    async with sf() as db:
        first = await wrong_question_service.record_wrong(
            db, uid, qid, wrong_answer="B", question_version_id=vid)
        second = await wrong_question_service.record_wrong(
            db, uid, qid, wrong_answer="C", question_version_id=vid)
        assert first.id == second.id
        assert second.review_count == 2
        assert second.wrong_answer == "C"
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_clears_ai_analysis_on_repeat(tmp_path):
    engine, sf = await _make_database(tmp_path)
    uid, qid, vid = await _seed(sf)
    async with sf() as db:
        first = await wrong_question_service.record_wrong(
            db, uid, qid, wrong_answer="B", question_version_id=vid)
        first.ai_analysis = {"content": "old"}
        await db.commit()
        second = await wrong_question_service.record_wrong(
            db, uid, qid, wrong_answer="C", question_version_id=vid)
        assert second.ai_analysis is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_stats_empty_user_returns_zeros(tmp_path):
    engine, sf = await _make_database(tmp_path)
    uid, _, _ = await _seed(sf)
    async with sf() as db:
        stats = await wrong_question_service.get_stats(db, uid)
    assert stats["total"] == 0
    assert stats["unmastered"] == 0
    assert stats["mastered"] == 0
    await engine.dispose()
