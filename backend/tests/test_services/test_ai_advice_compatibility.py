"""Real SQLite compatibility baseline for AI study-advice fallback behavior.

These tests exercise ``generate_advice`` against a real SQLite database with
no configured analysis model.  They verify the deterministic fallback path:
no LLM call, no AiChat persistence, zero tokens.  This is SQLite service-path
evidence only, not production PostgreSQL or real-AI verification.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all relationships before create_all
from app.core.database import Base
from app.models.admin import Subject
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services import ai_service


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'ai-advice.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(tmp_path, *, with_wrong: bool = False):
    engine, session_factory = await _make_database(tmp_path)
    async with session_factory() as db:
        subject = Subject(code="ds", name="数据结构", level=2, path="ds")
        db.add(subject)
        await db.flush()
        user = User(openid="advice-openid", nickname="tester")
        db.add(user)
        await db.flush()
        if with_wrong:
            question = Question(
                subject_id=subject.id,
                question_type="single_choice",
                content={"stem": "test"},
                options={"A": {"label": "A", "text": "a"}},
                answer="A",
                review_status="approved",
                is_active=True,
            )
            db.add(question)
            await db.flush()
            version = __import__(
                "app.models.admin", fromlist=["QuestionVersion"]
            ).QuestionVersion(
                question_id=question.id,
                version=1,
                question_type="single_choice",
                content={"stem": "test"},
                options={"A": {"label": "A", "text": "a"}},
                answer="A",
                difficulty=3,
                is_active=True,
                change_source="system",
            )
            db.add(version)
            await db.flush()
            question.current_version_id = version.id
            db.add(
                WrongQuestion(
                    user_id=user.id,
                    question_id=question.id,
                    question_version_id=version.id,
                    wrong_answer="B",
                    is_active=True,
                )
            )
        await db.commit()
        return engine, session_factory, user.id


@pytest.mark.asyncio
async def test_no_model_returns_fallback_without_persistence(tmp_path):
    """No analysis model configured → fallback, no AiChat, zero tokens."""
    engine, session_factory, user_id = await _seed(tmp_path)

    async with session_factory() as db:
        result = await ai_service.generate_advice(db, user_id)

    assert result["from_fallback"] is True
    assert result["model"] == "fallback"
    assert result["tokens_used"] == 0
    assert result["from_cache"] is False
    assert isinstance(result["content"], dict)

    async with session_factory() as db:
        chats = (await db.execute(select(AiChat))).scalars().all()
    assert len(chats) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_no_model_with_wrong_questions_still_fallback(tmp_path):
    """Active wrong questions exist but no model → still fallback, no AiChat."""
    engine, session_factory, user_id = await _seed(tmp_path, with_wrong=True)

    async with session_factory() as db:
        result = await ai_service.generate_advice(db, user_id)

    assert result["from_fallback"] is True
    assert result["model"] == "fallback"
    assert result["tokens_used"] == 0

    async with session_factory() as db:
        chats = (await db.execute(select(AiChat))).scalars().all()
    assert len(chats) == 0

    await engine.dispose()
