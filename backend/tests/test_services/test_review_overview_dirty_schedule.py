"""Real-SQLite contract for excluding dirty review schedules from overview counts."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all relationship targets
from app.core.database import Base
from app.core.time_utils import utcnow
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.models.review_scheduler import ReviewSchedule
from app.models.user import User
from app.services.review_scheduler import get_today_review_overview


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'review-overview.db'}"
    )
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _version(
    version_id: int,
    question_id: int,
    subject_id: int,
    version: int = 1,
) -> QuestionVersion:
    return QuestionVersion(
        id=version_id,
        question_id=question_id,
        version=version,
        subject_id=subject_id,
        question_type="single_choice",
        content={"text": f"question-{question_id}"},
        options={"A": "a"},
        answer="A",
        difficulty=3,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_overview_excludes_missing_and_mismatched_revision_schedules(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    due_at = utcnow() - timedelta(hours=1)
    try:
        async with session_factory() as db:
            db.add_all(
                [
                    User(id=1, openid="review-overview-user"),
                    Subject(
                        id=1,
                        code="exam408",
                        name="408",
                        level=1,
                        path="exam408",
                        is_active=True,
                    ),
                    Question(
                        id=1,
                        subject_id=1,
                        question_type="single_choice",
                        content={"text": "one"},
                        options={"A": "a"},
                        answer="A",
                    ),
                    Question(
                        id=2,
                        subject_id=1,
                        question_type="single_choice",
                        content={"text": "two"},
                        options={"A": "a"},
                        answer="A",
                    ),
                    _version(1, 1, 1),
                    _version(2, 2, 1),
                    # Revision exists but belongs to a different question.
                    _version(3, 2, 1, version=2),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    ReviewSchedule(
                        user_id=1,
                        question_id=1,
                        question_version_id=1,
                        subject_id=1,
                        next_review_at=due_at - timedelta(seconds=2),
                    ),
                    ReviewSchedule(
                        user_id=1,
                        question_id=2,
                        question_version_id=2,
                        subject_id=1,
                        next_review_at=due_at - timedelta(seconds=1),
                    ),
                    ReviewSchedule(
                        user_id=1,
                        question_id=999,
                        question_version_id=3,
                        subject_id=1,
                        next_review_at=due_at,
                    ),
                    ReviewSchedule(
                        user_id=1,
                        question_id=3,
                        question_version_id=4,
                        subject_id=1,
                        next_review_at=due_at,
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            overview = await get_today_review_overview(db, user_id=1)

        assert overview["today_due_count"] == 2
        assert overview["today_completed_count"] == 0
        assert overview["today_remaining_count"] == 2
        assert overview["all_question_ids"] == [1, 2]
        assert overview["remaining_question_ids"] == [1, 2]
    finally:
        await engine.dispose()
