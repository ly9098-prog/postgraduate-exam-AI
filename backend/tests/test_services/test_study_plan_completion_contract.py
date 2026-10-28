"""Contract for today's study-plan completion facts against a real SQLite session."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.core.time_utils import current_study_day
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAttempt, ExamPaper
from app.models.pomodoro import (
    PomodoroSession,
    PomodoroSubjectAllocation,
)
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord
from app.models.study_plan import StudyPlan
from app.models.user import User
from app.services import study_plan_rules as rules
from app.services import study_plan_service as service
from app.services.study_plan_completion import load_today_completion

TODAY = date(2026, 10, 28)
DAY_START_MINUTE = 0
ALL_408_IDS = [1, 2, 3, 4]
CORE_408_IDS = [1]


async def _make_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'plan-completion.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 28, hour, minute)


def _seed_subjects() -> list[Subject]:
    exams = [("exam408", "408", 1, None)]
    codes = ("data_structure", "computer_organization", "operating_system", "computer_network")
    exams.extend((code, code, 2, 1) for code in codes)
    return [
        Subject(id=index, code=code, name=name, level=level, parent_id=parent, path=code)
        for index, (code, name, level, parent) in enumerate(exams, start=1)
    ]


def _seed_activity(user_id: int) -> list:
    rows: list = [
        User(id=user_id, openid=f"plan-completion-{user_id}"),
        *_seed_subjects(),
        Question(id=1, subject_id=1, content="题干", answer="A"),
        QuestionVersion(
            id=1,
            question_id=1,
            version=1,
            subject_id=1,
            content="题干",
            answer="A",
            difficulty=1,
            created_at=_at(9),
        ),
    ]
    rows.extend(
        ReviewRecord(
            id=index,
            user_id=user_id,
            question_id=1,
            question_version_id=1,
            request_id=f"review-{index}",
            occurrence_seq=index,
            rating=3,
            reviewed_at=_at(9, index),
        )
        for index in range(1, 4)
    )
    rows.extend(
        [
            PracticeSession(
                id=1,
                user_id=user_id,
                subject_id=1,
                request_id="practice-smart",
                mode="smart",
                status="completed",
                started_at=_at(8),
                finished_at=_at(8, 10),
                duration_sec=600,
                created_at=_at(8, 10),
            ),
            PracticeSession(
                id=2,
                user_id=user_id,
                subject_id=1,
                request_id="practice-weak",
                mode="random",
                status="completed",
                started_at=_at(10),
                finished_at=_at(10, 10),
                duration_sec=600,
                created_at=_at(10, 10),
            ),
            ExamPaper(id=1, title="408 模拟卷", paper_type="mock_choice"),
            ExamAttempt(
                id=1,
                paper_id=1,
                paper_version=1,
                user_id=user_id,
                request_id="exam-1",
                status="submitted",
                started_at=_at(7),
                submitted_at=_at(7, 5),
                duration_sec=300,
                created_at=_at(7),
                updated_at=_at(7, 5),
            ),
        ]
    )
    pomodoro = PomodoroSession(
        id=1,
        user_id=user_id,
        subject_id=1,
        status="completed",
        start_time=_at(10),
        end_time=_at(10, 30),
        actual_duration=1800,
        total_paused_sec=0,
        created_at=_at(10),
    )
    pomodoro.subject_allocations = [
        PomodoroSubjectAllocation(
            session_id=1,
            subject_id=index,
            weight_basis_points=2500,
            subject_code_snapshot=f"core-{index}",
            subject_name_snapshot=f"core-{index}",
        )
        for index in range(1, 5)
    ]
    rows.append(pomodoro)
    return rows


@pytest.mark.asyncio
async def test_today_completion_matches_durable_facts_and_pomodoro_supplement(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        async with session_factory() as db:
            db.add_all(_seed_activity(1))
            await db.commit()

        async with session_factory() as db:
            completed, focus_minutes, supplement_minutes = await load_today_completion(
                db,
                1,
                today=TODAY,
                planned={"review": 15, "weakness": 10, "new": 20, "exam": 10},
                all_408_ids=ALL_408_IDS,
                core_408_ids=CORE_408_IDS,
                day_start_minute=DAY_START_MINUTE,
            )
            mirrored = await service._today_completion(
                db,
                1,
                today=TODAY,
                planned={"review": 15, "weakness": 10, "new": 20, "exam": 10},
                all_408_ids=ALL_408_IDS,
                core_408_ids=CORE_408_IDS,
                day_start_minute=DAY_START_MINUTE,
            )
    finally:
        await engine.dispose()

    assert completed == mirrored[0]
    assert (focus_minutes, supplement_minutes) == (mirrored[1], mirrored[2])
    # 3 reviews → 2 minutes; smart practice 10; exam 5; 10 non-smart minutes
    # distributed 10:20 between weakness/new → weakness 3 / new 7.
    # Pomodoro keeps the raw 30 focus minutes and drops the 10 minutes already
    # covered by the practice window when measuring the supplement.
    assert completed == {"review": 2, "weakness": 3, "new": 17, "exam": 5}
    assert (focus_minutes, supplement_minutes) == (30, 20)
    assert (
        service._credit_supplemental_focus(
            completed=completed,
            target_minutes=60,
            supplement_minutes=supplement_minutes,
        )
        == 20
    )


def test_non_smart_practice_distributes_by_planned_weakness_and_new():
    cases = [
        ({"weakness": 0, "new": 0}, {"weakness": 0, "new": 6}),
        ({"weakness": 10, "new": 0}, {"weakness": 6, "new": 0}),
        ({"weakness": 0, "new": 20}, {"weakness": 0, "new": 6}),
        ({"weakness": 10, "new": 20}, {"weakness": 2, "new": 4}),
    ]
    for planned, expected in cases:
        completed = rules.completed_by_category(
            review_count=0,
            smart_minutes=0,
            exam_minutes=0,
            other_minutes=6,
            planned=planned,
        )
        assert (completed["weakness"], completed["new"]) == (
            expected["weakness"],
            expected["new"],
        )


def test_review_rounding_and_study_day_window_stay_unchanged():
    for review_count, expected in ((0, 0), (1, 1), (2, 1), (3, 2), (4, 2)):
        completed = rules.completed_by_category(
            review_count=review_count,
            smart_minutes=0,
            exam_minutes=0,
            other_minutes=0,
            planned={},
        )
        assert completed["review"] == expected

    assert (
        rules.study_day_seconds(
            start=datetime(2026, 10, 28, 15, 30),
            end=datetime(2026, 10, 28, 16, 30),
            duration_sec=3600,
            target_day=TODAY,
            day_start_minute=DAY_START_MINUTE,
        )
        == 1800
    )


def test_supplement_credit_is_capped_by_unfilled_target():
    assert (
        rules.credit_supplemental_focus(
            completed={"review": 20, "weakness": 20, "new": 20, "exam": 20},
            target_minutes=90,
            supplement_minutes=30,
        )
        == 10
    )
    assert (
        rules.credit_supplemental_focus(
            completed={"review": 0, "weakness": 0, "new": 0, "exam": 0},
            target_minutes=45,
            supplement_minutes=90,
        )
        == 45
    )


@pytest.mark.asyncio
async def test_overview_response_shape_for_configured_and_missing_plan(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        today = current_study_day(DAY_START_MINUTE)
        async with session_factory() as db:
            db.add_all(
                [
                    User(id=1, openid="overview-user"),
                    *_seed_subjects(),
                    StudyPlan(
                        id=1,
                        user_id=1,
                        target_date=today + timedelta(days=60),
                        daily_minutes=90,
                        weekly_days=6,
                        priority_mode="balanced",
                        revision=1,
                        is_active=True,
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            configured = await service.get_study_plan_overview(db, 1)
            missing = await service.get_study_plan_overview(db, 2)
    finally:
        await engine.dispose()

    assert configured["configured"] is True
    assert configured["date"] == today
    assert configured["countdown"]["days_remaining"] == 60
    assert configured["countdown"]["phase"] == "steady"
    assert configured["weekly"] == {
        "week_start": today - timedelta(days=today.weekday()),
        "week_end": today - timedelta(days=today.weekday()) + timedelta(days=6),
        "target_days": 6,
        "active_days": 0,
        "remaining_days": 6,
        "target_met": False,
    }
    assert configured["today"]["target_minutes"] == 90
    assert configured["today"]["completed_minutes"] == 0
    assert configured["today"]["remaining_minutes"] == 90
    assert configured["today"]["completion_percent"] == 0
    assert configured["today"]["focus_minutes"] == 0
    assert [
        item["category"] for item in configured["today"]["allocations"]
    ] == ["review", "weakness", "new", "exam"]

    assert missing["configured"] is False
    assert missing["suggested_defaults"] == {
        "daily_minutes": 90,
        "weekly_days": 6,
        "priority_mode": "balanced",
    }
