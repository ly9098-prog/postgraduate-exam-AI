from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.user import User
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.mastery_service import (
    update_user_knowledge_state_after_answer,
)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'mastery-concurrency.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="mastery-user-1"),
                Subject(id=1, code="mastery", name="Mastery", path="mastery"),
                KnowledgePoint(
                    id=1,
                    subject_id=1,
                    name="导数",
                    normalized_name="导数",
                    aliases=[],
                    is_active=True,
                ),
                QuestionVersion(
                    id=1,
                    question_id=1,
                    version=1,
                    subject_id=1,
                    question_type="single_choice",
                    content={"text": "1"},
                    options={"A": "A"},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                ),
                QuestionVersionKnowledgePoint(
                    question_version_id=1,
                    knowledge_point_id=1,
                    position=0,
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_mastery_claim_reloads_winner_without_double_count(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        async with session_factory() as db:
            db.add(
                UserKnowledgeState(
                    user_id=1,
                    subject_id=1,
                    knowledge_point_id=1,
                    attempt_count=0,
                    correct_count=0,
                    wrong_count=0,
                    accuracy=0.0,
                    mastery_score=50.0,
                    weakness_level="observing",
                    confidence=0.0,
                    recent_answer_count=0,
                    recent_correct_count=0,
                    recent_wrong_count=0,
                )
            )
            await db.commit()

        async with session_factory() as db:
            result = await update_user_knowledge_state_after_answer(
                db,
                user_id=1,
                question_id=1,
                is_correct=True,
                question_version_id=1,
                used_time=60,
            )
            await db.commit()

        async with session_factory() as db:
            state = await db.scalar(
                select(UserKnowledgeState).where(
                    UserKnowledgeState.user_id == 1,
                    UserKnowledgeState.knowledge_point_id == 1,
                )
            )
            count = await db.scalar(
                select(func.count(UserKnowledgeState.id)).where(
                    UserKnowledgeState.user_id == 1,
                    UserKnowledgeState.knowledge_point_id == 1,
                )
            )

        assert result["created"] == 0
        assert result["updated"] == 1
        assert count == 1
        assert state.attempt_count == 1
        assert state.correct_count == 1
    finally:
        await engine.dispose()
