"""Real SQLite compatibility baseline for AI error-analysis revision guard.

These tests exercise the ``analyze_error`` revision-drift safety boundary
against a real SQLite database.  They do NOT call any LLM: the revision guard
returns deterministically before the cache/LLM path.  This is SQLite service-
path evidence only, not production PostgreSQL or real-AI verification.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all relationships before create_all
from app.core.database import Base
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services import ai_service


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'ai-analysis.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_subject_user(session_factory) -> tuple[int, int]:
    async with session_factory() as db:
        subject = Subject(
            code="ds", name="数据结构", level=2, path="ds", sort_order=0,
        )
        db.add(subject)
        await db.flush()
        user = User(openid="test-openid", nickname="tester")
        db.add(user)
        await db.flush()
        await db.commit()
        return subject.id, user.id


def _make_question(
    subject_id: int,
    *,
    answer: str = "B",
    options: dict | None = None,
    current_version_id: int | None = None,
) -> Question:
    return Question(
        subject_id=subject_id,
        question_type="single_choice",
        content={"stem": "以下哪个是线性结构？"},
        options=options or {
            "A": {"label": "A", "text": "树"},
            "B": {"label": "B", "text": "栈"},
            "C": {"label": "C", "text": "图"},
            "D": {"label": "D", "text": "堆"},
        },
        answer=answer,
        review_status="approved",
        is_active=True,
        current_version_id=current_version_id,
    )


def _make_version(
    question_id: int,
    version: int,
    *,
    answer: str = "B",
    options: dict | None = None,
) -> QuestionVersion:
    return QuestionVersion(
        question_id=question_id,
        version=version,
        question_type="single_choice",
        content={"stem": "以下哪个是线性结构？"},
        options=options or {
            "A": {"label": "A", "text": "树"},
            "B": {"label": "B", "text": "栈"},
            "C": {"label": "C", "text": "图"},
            "D": {"label": "D", "text": "堆"},
        },
        answer=answer,
        difficulty=3,
        is_active=True,
        change_source="system",
    )


@pytest.mark.asyncio
async def test_revision_drift_returns_guard_without_llm(tmp_path):
    """Options changed between wrong-attempt version and current → revision_guard."""
    engine, session_factory = await _make_database(tmp_path)
    subject_id, user_id = await _seed_subject_user(session_factory)

    async with session_factory() as db:
        question = _make_question(subject_id)
        db.add(question)
        await db.flush()

        old_version = _make_version(question.id, 1, answer="C")
        db.add(old_version)
        await db.flush()

        # Point the question to a *new* version that does not exist yet —
        # the guard fires on version_id mismatch before any version lookup.
        question.current_version_id = old_version.id + 999
        wq = WrongQuestion(
            user_id=user_id,
            question_id=question.id,
            question_version_id=old_version.id,
            wrong_answer="C",
        )
        db.add(wq)
        await db.commit()
        wq_id = wq.id

    async with session_factory() as db:
        result = await ai_service.analyze_error(db, user_id, wq_id)

    assert result["model"] == "revision_guard"
    assert result["revision_guarded"] is True
    assert result["tokens_used"] == 0
    assert result["from_cache"] is False
    assert "mistake_diagnosis" in result["content"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_revision_signature_match_does_not_guard(tmp_path):
    """Same answer/options semantics across versions → no revision_guard flag.

    The guard returns early only when signatures differ.  When they match the
    function continues past the guard into the cache/LLM path.  We assert the
    negative: the result is NOT a revision_guard response.  Since no LLM is
    configured the call will either hit a fallback or raise, but the key
    contract is that ``revision_guarded`` is absent or False.
    """
    engine, session_factory = await _make_database(tmp_path)
    subject_id, user_id = await _seed_subject_user(session_factory)

    async with session_factory() as db:
        question = _make_question(subject_id)
        db.add(question)
        await db.flush()

        old_version = _make_version(question.id, 1)
        new_version = _make_version(question.id, 2)
        db.add_all([old_version, new_version])
        await db.flush()

        question.current_version_id = new_version.id
        wq = WrongQuestion(
            user_id=user_id,
            question_id=question.id,
            question_version_id=old_version.id,
            wrong_answer="C",
        )
        db.add(wq)
        await db.commit()
        wq_id = wq.id

    async with session_factory() as db:
        result = await ai_service.analyze_error(db, user_id, wq_id)

    # Signatures match → guard does not fire.  The call proceeds to the
    # cache/LLM path; without a configured model it returns a fallback or
    # cache-miss result, but never a revision_guard.
    assert result.get("model") != "revision_guard"
    assert result.get("revision_guarded") is not True

    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_wrong_question_raises(tmp_path):
    """Non-existent wrong_question_id → ValueError before any version logic."""
    engine, session_factory = await _make_database(tmp_path)
    _, user_id = await _seed_subject_user(session_factory)

    async with session_factory() as db:
        with pytest.raises(ValueError, match="错题记录不存在"):
            await ai_service.analyze_error(db, user_id, 99999)

    await engine.dispose()


@pytest.mark.asyncio
async def test_same_version_does_not_guard(tmp_path):
    """current_version_id == wrong_version_id → no drift, no guard."""
    engine, session_factory = await _make_database(tmp_path)
    subject_id, user_id = await _seed_subject_user(session_factory)

    async with session_factory() as db:
        question = _make_question(subject_id)
        db.add(question)
        await db.flush()

        version = _make_version(question.id, 1)
        db.add(version)
        await db.flush()

        question.current_version_id = version.id
        wq = WrongQuestion(
            user_id=user_id,
            question_id=question.id,
            question_version_id=version.id,
            wrong_answer="C",
        )
        db.add(wq)
        await db.commit()
        wq_id = wq.id

    async with session_factory() as db:
        result = await ai_service.analyze_error(db, user_id, wq_id)

    assert result.get("model") != "revision_guard"
    assert result.get("revision_guarded") is not True

    await engine.dispose()
