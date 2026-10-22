from __future__ import annotations

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.models.user import User
from app.models.user_adaptive_profile import UserAdaptiveProfile
from app.models.user_knowledge_adaptive_state import UserKnowledgeAdaptiveState
from app.models.user_question_difficulty_state import UserQuestionDifficultyState
from app.services.adaptive_learning_service import (
    update_knowledge_interval_factor,
    update_question_difficulty_state,
    update_user_interval_factor,
)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'adaptive-concurrency.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="adaptive-user-1"),
                Subject(id=1, code="adaptive", name="Adaptive", path="adaptive"),
            ]
        )
        await db.flush()
        db.add(
            Question(
                id=1,
                subject_id=1,
                question_type="single_choice",
                content={"text": "1"},
                options={"A": "A"},
                answer="A",
                difficulty=3,
                review_status="approved",
                is_active=True,
            )
        )
        await db.flush()
        db.add(
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
            )
        )
        await db.commit()


async def _insert_winner(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                UserAdaptiveProfile(user_id=1),
                UserKnowledgeAdaptiveState(user_id=1, knowledge_point_id=1),
                UserQuestionDifficultyState(user_id=1, question_id=1),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_profile_claim_reloads_winner_without_double_count(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        await _insert_winner(session_factory)
        async with session_factory() as db:
            factor = await update_user_interval_factor(
                db,
                user_id=1,
                is_due_review=True,
                is_correct=True,
                is_overdue_review=False,
            )
            await db.commit()

        async with session_factory() as db:
            profile = await db.scalar(
                select(UserAdaptiveProfile).where(UserAdaptiveProfile.user_id == 1)
            )
            count = await db.scalar(
                select(func.count(UserAdaptiveProfile.id)).where(
                    UserAdaptiveProfile.user_id == 1
                )
            )

        assert factor == pytest.approx(1.04)
        assert count == 1
        assert profile.recent_due_count == 1
        assert profile.recent_due_correct_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_claim_reloads_winner_without_double_count(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        await _insert_winner(session_factory)
        async with session_factory() as db:
            await update_knowledge_interval_factor(
                db,
                user_id=1,
                knowledge_point_ids=[1],
                is_due_review=True,
                is_correct=True,
                is_overdue_review=False,
            )
            await db.commit()

        async with session_factory() as db:
            state = await db.scalar(
                select(UserKnowledgeAdaptiveState).where(
                    UserKnowledgeAdaptiveState.user_id == 1,
                    UserKnowledgeAdaptiveState.knowledge_point_id == 1,
                )
            )
            count = await db.scalar(
                select(func.count(UserKnowledgeAdaptiveState.id)).where(
                    UserKnowledgeAdaptiveState.user_id == 1,
                    UserKnowledgeAdaptiveState.knowledge_point_id == 1,
                )
            )

        assert count == 1
        assert state.due_review_count == 1
        assert state.due_review_correct_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_difficulty_claim_reloads_winner_without_double_count(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        await _insert_winner(session_factory)
        async with session_factory() as db:
            await update_question_difficulty_state(
                db,
                user_id=1,
                question_id=1,
                is_correct=True,
                answer_time_seconds=60,
                expected_time_seconds=60,
                is_overdue_review=False,
            )
            await db.commit()

        async with session_factory() as db:
            state = await db.scalar(
                select(UserQuestionDifficultyState).where(
                    UserQuestionDifficultyState.user_id == 1,
                    UserQuestionDifficultyState.question_id == 1,
                )
            )
            count = await db.scalar(
                select(func.count(UserQuestionDifficultyState.id)).where(
                    UserQuestionDifficultyState.user_id == 1,
                    UserQuestionDifficultyState.question_id == 1,
                )
            )

        assert count == 1
        assert state.answer_count == 1
        assert state.correct_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_claim_reuses_an_already_started_sqlite_transaction(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        async with session_factory() as db:
            await db.execute(
                update(User).where(User.id == 1).values(nickname="dirty")
            )
            factor = await update_user_interval_factor(
                db,
                user_id=1,
                is_due_review=True,
                is_correct=True,
                is_overdue_review=False,
            )
            await db.rollback()

        async with session_factory() as db:
            count = await db.scalar(
                select(func.count(UserAdaptiveProfile.id)).where(
                    UserAdaptiveProfile.user_id == 1
                )
            )

        assert factor == pytest.approx(1.04)
        assert count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_batch_claim_reloads_winner_without_double_count(
    tmp_path,
):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        await _insert_winner(session_factory)
        async with session_factory() as db:
            await update_knowledge_interval_factor(
                db,
                user_id=1,
                knowledge_point_ids=[1, 1],
                is_due_review=True,
                is_correct=True,
                is_overdue_review=False,
            )
            await db.commit()

        async with session_factory() as db:
            state = await db.scalar(
                select(UserKnowledgeAdaptiveState).where(
                    UserKnowledgeAdaptiveState.user_id == 1,
                    UserKnowledgeAdaptiveState.knowledge_point_id == 1,
                )
            )
            count = await db.scalar(
                select(func.count(UserKnowledgeAdaptiveState.id)).where(
                    UserKnowledgeAdaptiveState.user_id == 1,
                    UserKnowledgeAdaptiveState.knowledge_point_id == 1,
                )
            )

        assert count == 1
        assert state.due_review_count == 1
    finally:
        await engine.dispose()
