"""Frozen-revision topic fallbacks must execute against a real database."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register relationships before create_all
from app.core.database import Base
from app.models.admin import (
    QuestionVersion,
    QuestionVersionKnowledgePoint,
    Subject,
)
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.syllabus import SyllabusKnowledgePoint, SyllabusVersion
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services import dashboard_insights_service as svc


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'fallback-topics.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _question(question_id: int) -> list:
    return [
        Question(
            id=question_id,
            subject_id=2,
            question_type="single_choice",
            content={},
            answer="A",
            difficulty=3,
            is_active=True,
        ),
        QuestionVersion(
            id=question_id,
            question_id=question_id,
            version=1,
            subject_id=2,
            question_type="single_choice",
            content={},
            answer="A",
            difficulty=3,
            is_active=True,
        ),
    ]


def _wrong(user_id, question_id, *, review_count=0, mastered=False, active=True):
    return WrongQuestion(
        user_id=user_id,
        question_id=question_id,
        question_version_id=question_id,
        review_count=review_count,
        mastered=mastered,
        is_active=active,
    )


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="fallback-user-1"),
                User(id=2, openid="fallback-user-2"),
                Subject(id=1, code="exam408", name="408", path="exam408", level=1),
                Subject(
                    id=2,
                    parent_id=1,
                    code="ds",
                    name="数据结构",
                    path="exam408/ds",
                    level=2,
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                KnowledgePoint(id=1, subject_id=2, name="当前名", normalized_name="a"),
                KnowledgePoint(id=2, subject_id=2, name="B名", normalized_name="b"),
                KnowledgePoint(id=3, subject_id=2, name="C名", normalized_name="c"),
                SyllabusVersion(
                    id=1,
                    code="s2026",
                    name="2026",
                    root_subject_id=1,
                    effective_year=2026,
                    status="draft",
                ),
            ]
        )
        await db.flush()
        db.add(
            SyllabusKnowledgePoint(
                id=1,
                syllabus_version_id=1,
                knowledge_point_id=1,
                subject_id=2,
                name_snapshot="冻结名",
                normalized_name_snapshot="frozen",
            )
        )
        for question_id in range(10, 17):
            db.add_all(_question(question_id))
        await db.flush()
        db.add_all(
            [
                QuestionVersionKnowledgePoint(
                    question_version_id=10,
                    knowledge_point_id=1,
                    syllabus_knowledge_point_id=1,
                ),
                *[
                    QuestionVersionKnowledgePoint(
                        question_version_id=question_id, knowledge_point_id=2
                    )
                    for question_id in (11, 12, 13, 14, 15)
                ],
                QuestionVersionKnowledgePoint(
                    question_version_id=16, knowledge_point_id=3
                ),
                _wrong(1, 10, review_count=1),
                _wrong(1, 11, review_count=1),
                _wrong(1, 12, review_count=1),
                _wrong(1, 13, review_count=1, mastered=True),
                _wrong(2, 14, review_count=1),
                _wrong(1, 15, review_count=1, active=False),
                _wrong(1, 16, review_count=1),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_weak_topic_fallback_runs_and_uses_frozen_names(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        async with session_factory() as db:
            result = await svc.compute_weak_topic_ranking(db, 1)
    finally:
        await engine.dispose()

    assert [(i["name"], i["wrong_count"]) for i in result["items"]] == [
        ("B名", 2),
        ("冻结名", 1),
        ("C名", 1),
    ]
    assert all(i["knowledge_point_id"] == 0 for i in result["items"])


@pytest.mark.asyncio
async def test_repeat_wrong_top_topics_runs_and_filters(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        async with session_factory() as db:
            result = await svc.compute_repeat_wrong_analysis(db, 1)
    finally:
        await engine.dispose()

    assert result["top_repeat_topics"] == [
        {"name": "B名", "count": 2},
        {"name": "冻结名", "count": 1},
        {"name": "C名", "count": 1},
    ]
