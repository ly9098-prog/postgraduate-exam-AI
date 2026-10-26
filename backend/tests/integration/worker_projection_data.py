"""Synthetic immutable practice events and independent SQL observations."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register relationships
from app.core.time_utils import utcnow
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.user import User

USER_ID = 9001
FIRST = 9001
SECOND = 9002


async def seed_records(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all(
            [
                User(id=USER_ID, openid="owned-worker-synthetic"),
                Subject(
                    id=9001, code="owned-worker", name="Synthetic", path="owned-worker"
                ),
            ]
        )
        await db.flush()
        for identity in (FIRST, SECOND):
            await seed_question(db, identity)
        await db.commit()


async def seed_question(db, identity):
    question = Question(
        id=identity,
        subject_id=9001,
        question_type="single_choice",
        content={"text": "Synthetic worker fixture"},
        options={"A": "Synthetic"},
        answer="B",
        review_status="approved",
        is_active=True,
    )
    db.add(question)
    db.add(
        KnowledgePoint(
            id=identity,
            subject_id=9001,
            name=f"synthetic-{identity}",
            normalized_name=f"synthetic-{identity}",
        )
    )
    await db.flush()
    db.add(
        QuestionVersion(
            id=identity + 10000,
            question_id=identity,
            version=1,
            subject_id=9001,
            question_type="single_choice",
            content={"text": "Synthetic worker fixture"},
            options={"A": "Synthetic"},
            answer="A",
            difficulty=3,
            is_active=True,
        )
    )
    await db.flush()
    question.current_version_id = identity + 10000
    db.add(
        QuestionVersionKnowledgePoint(
            question_version_id=identity + 10000,
            knowledge_point_id=identity,
        )
    )
    await seed_record(db, identity)


async def seed_record(db, identity):
    db.add(
        PracticeRecord(
            id=identity,
            user_id=USER_ID,
            question_id=identity,
            question_version_id=identity + 10000,
            subject_id=9001,
            user_answer="A",
            question_type="single_choice",
            is_correct=True,
            used_time=7,
            answered_at=utcnow(),
            mode="random",
            projection_state="pending",
        )
    )
    await db.flush()


def database_engine(runtime):
    return create_async_engine(runtime.postgres.url, echo=False)


async def observe(engine, identity):
    async with engine.connect() as connection:
        projection = await connection.scalar(
            select(PracticeRecord.projection_state).where(
                PracticeRecord.id == identity
            ),
        )
        behavior = await rows(
            connection,
            "SELECT question_version_id, time_spent_sec, is_final_correct, "
            "user_answer, correct_answer FROM answer_behaviors "
            "WHERE practice_record_id = :id ORDER BY id",
            identity,
        )
        review = await rows(
            connection,
            "SELECT answer_count, correct_count, wrong_count, box_level "
            "FROM user_question_state WHERE user_id = :uid AND question_id = :id",
            identity,
        )
        mastery = await rows(
            connection,
            "SELECT attempt_count, correct_count, wrong_count, mastery_score "
            "FROM user_knowledge_states WHERE user_id = :uid AND knowledge_point_id = :id",
            identity,
        )
        adaptive = await rows(
            connection,
            "SELECT answer_count, correct_count, wrong_count, personal_difficulty_score "
            "FROM user_question_difficulty_state WHERE user_id = :uid AND question_id = :id",
            identity,
        )
    return {
        "projection": projection,
        "behavior": behavior,
        "review": review,
        "mastery": mastery,
        "adaptive": adaptive,
    }


async def rows(connection, query, identity):
    result = await connection.execute(text(query), {"id": identity, "uid": USER_ID})
    return [dict(row) for row in result.mappings().all()]


def assert_projected(state, identity):
    assert state == {
        "projection": "completed",
        "behavior": [
            {
                "question_version_id": identity + 10000,
                "time_spent_sec": 7,
                "is_final_correct": True,
                "user_answer": "A",
                "correct_answer": "A",
            }
        ],
        "review": [
            {
                "answer_count": 1,
                "correct_count": 1,
                "wrong_count": 0,
                "box_level": 1,
            }
        ],
        "mastery": [
            {
                "attempt_count": 1,
                "correct_count": 1,
                "wrong_count": 0,
                "mastery_score": 56.0,
            }
        ],
        "adaptive": [
            {
                "answer_count": 1,
                "correct_count": 1,
                "wrong_count": 0,
                "personal_difficulty_score": 43.0,
            }
        ],
    }


def assert_pending(state):
    assert state == {
        "projection": "pending",
        "behavior": [],
        "review": [],
        "mastery": [],
        "adaptive": [],
    }
