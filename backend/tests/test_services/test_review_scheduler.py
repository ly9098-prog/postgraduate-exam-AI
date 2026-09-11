"""Stage 12: SM-2 复习调度系统 — 单元测试。"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all ORM models are registered so Subject's string relationships
# (practice_records, answer_behaviors, review_schedules, ...) resolve at
# mapper configuration time (see app/models/admin.py Subject).
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.import_batch_job import ImportBatchJob  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.pomodoro import PomodoroSession  # noqa: F401
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.tag import Tag  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401
from app.services.review_scheduler import (
    auto_schedule_wrong_question,
    get_review_history,
    get_review_stats,
    get_today_review,
    submit_review,
)
from app.services.sm2_service import calc_sm2

# ── Helpers ──


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock()
    return db


def _make_execute_result(**methods):
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        elif method == "one":
            mock_result.one.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _mock_execute_sequence(db, *results):
    db.execute.side_effect = [_make_execute_result(**r) for r in results]


def _make_schedule_mock(
    id=1,
    user_id=1,
    question_id=10,
    subject_id=1,
    interval=5,
    ease_factor=2.5,
    repetitions=2,
    next_review_at=None,
):
    s = MagicMock()
    s.id = id
    s.user_id = user_id
    s.question_id = question_id
    s.question_version_id = 1000 + question_id
    s.occurrence_seq = 0
    s.subject_id = subject_id
    s.interval = interval
    s.ease_factor = ease_factor
    s.repetitions = repetitions
    s.mastered = False
    s.is_active = True
    s.next_review_at = next_review_at or datetime.now(UTC) - timedelta(days=1)
    s.last_reviewed_at = None
    return s


def _make_question_mock(
    id=10,
    subject_id=1,
    subject_code="math2",
    question_type="single_choice",
    content=None,
    options=None,
    answer="A",
    analysis="test",
):
    q = MagicMock()
    q.id = id
    q.subject_id = subject_id
    q.subject_ref.code = subject_code
    q.subject_ref.name = subject_code
    q.question_type = question_type
    q.content = content or {"text": "Test question stem"}
    q.options = options or {"A": "option a", "B": "option b"}
    q.answer = answer
    q.analysis = analysis
    return q


def _make_revision_mock(question_id=10, subject_id=1):
    revision = MagicMock()
    revision.id = 1000 + question_id
    revision.question_id = question_id
    revision.subject_id = subject_id
    revision.subject_ref = MagicMock(code="math2", name="数学二")
    revision.question_type = "single_choice"
    revision.content = {"text": "Test question stem"}
    revision.options = {"A": "option a", "B": "option b"}
    revision.image_url = None
    revision.answer = "A"
    return revision


# ── SM-2 Algorithm Tests (pure function) ──


class TestSM2Algorithm:
    """测试核心 SM-2 算法（复用 sm2_service.calc_sm2）。"""

    def test_rating_5_max_growth(self):
        result = calc_sm2(quality=5, efactor=2.5, interval=10, repetitions=3)
        assert result["interval"] == round(10 * 2.5)  # 25
        assert result["efactor"] >= 2.5  # EF should increase for quality=5
        assert result["repetitions"] == 4

    def test_rating_4(self):
        result = calc_sm2(quality=4, efactor=2.5, interval=6, repetitions=2)
        assert result["interval"] == round(6 * 2.5)
        assert result["repetitions"] == 3

    def test_rating_3_pass_threshold(self):
        result = calc_sm2(quality=3, interval=6, repetitions=2)
        assert result["interval"] == round(6 * 2.5)
        assert result["repetitions"] == 3

    def test_rating_2_wrong(self):
        result = calc_sm2(quality=2, interval=6, repetitions=3)
        assert result["interval"] == 1
        assert result["repetitions"] == 0

    def test_rating_0_complete_blackout(self):
        result = calc_sm2(quality=0, interval=30, repetitions=5)
        assert result["interval"] == 1
        assert result["repetitions"] == 0
        assert result["efactor"] <= 2.5  # EF should decrease

    def test_ef_minimum_1_3(self):
        """EF 不应低于 1.3。"""
        # Repeatedly apply low quality to drive EF down
        ef = 2.5
        for _ in range(50):
            result = calc_sm2(quality=0, efactor=ef, interval=1, repetitions=0)
            ef = result["efactor"]
        assert ef >= 1.3

    def test_first_review_interval_1(self):
        result = calc_sm2(quality=4, interval=0, repetitions=0)
        assert result["interval"] == 1
        assert result["repetitions"] == 1

    def test_second_review_interval_6(self):
        result = calc_sm2(quality=4, interval=1, repetitions=1)
        assert result["interval"] == 6
        assert result["repetitions"] == 2

    def test_third_review_depends_on_ef(self):
        result = calc_sm2(quality=4, interval=6, repetitions=2)
        assert result["interval"] == round(6 * 2.5)
        assert result["repetitions"] == 3

    def test_repetitions_reset_on_wrong(self):
        result = calc_sm2(quality=1, interval=30, repetitions=10)
        assert result["repetitions"] == 0

    def test_ef_decrease_on_low_rating(self):
        result_before = calc_sm2(quality=5, efactor=2.5, interval=1, repetitions=1)
        ef_after_good = result_before["efactor"]

        result_after = calc_sm2(
            quality=1, efactor=ef_after_good, interval=1, repetitions=0
        )
        assert result_after["efactor"] < ef_after_good

    def test_invalid_rating_raises(self):
        with pytest.raises(ValueError):
            calc_sm2(quality=6)
        with pytest.raises(ValueError):
            calc_sm2(quality=-1)

    def test_next_review_date_is_future(self):
        result = calc_sm2(quality=4, interval=6, repetitions=2)
        assert result["next_review_date"] >= date.today()


# ── get_today_review Tests ──


class TestGetTodayReview:
    def test_returns_due_reviews(self):
        db = _make_mock_db()
        now = datetime.now(UTC)
        schedules = [
            _make_schedule_mock(
                id=1, question_id=10, next_review_at=now - timedelta(days=2)
            ),
            _make_schedule_mock(
                id=2, question_id=11, next_review_at=now - timedelta(hours=1)
            ),
        ]
        db.scalar.side_effect = [2]
        result = MagicMock()
        result.all.return_value = schedules
        db.scalars.return_value = result
        with (
            patch(
                "app.services.review_scheduler._active_408_subject_ids",
                new=AsyncMock(return_value={1}),
            ),
            patch(
                "app.services.review_scheduler.load_revision_views",
                new=AsyncMock(
                    return_value={
                        1010: _make_revision_mock(10),
                        1011: _make_revision_mock(11),
                    }
                ),
            ),
        ):
            result = asyncio.run(get_today_review(db, user_id=1))

        assert result["total_today"] == 2
        assert len(result["questions"]) == 2
        assert result["questions"][0]["schedule_id"] == 1
        assert result["questions"][0]["question_id"] == 10
        assert "answer" not in result["questions"][0]  # 不返回答案

    def test_empty_when_no_due(self):
        db = _make_mock_db()
        db.scalar.return_value = 0
        result = MagicMock()
        result.all.return_value = []
        db.scalars.return_value = result
        with (
            patch(
                "app.services.review_scheduler._active_408_subject_ids",
                new=AsyncMock(return_value={1}),
            ),
            patch(
                "app.services.review_scheduler.load_revision_views",
                new=AsyncMock(return_value={}),
            ),
        ):
            result = asyncio.run(get_today_review(db, user_id=1))

        assert result["total_today"] == 0
        assert result["questions"] == []

    def test_subject_filter(self):
        db = _make_mock_db()
        now = datetime.now(UTC)
        schedules = [
            _make_schedule_mock(
                id=1,
                question_id=10,
                subject_id=1,
                next_review_at=now - timedelta(days=1),
            ),
            _make_schedule_mock(
                id=2,
                question_id=11,
                subject_id=2,
                next_review_at=now - timedelta(days=1),
            ),
        ]
        db.scalar.return_value = 1
        result = MagicMock()
        result.all.return_value = [schedules[0]]
        db.scalars.return_value = result
        with (
            patch(
                "app.services.review_scheduler._active_408_subject_ids",
                new=AsyncMock(return_value={1, 2}),
            ),
            patch(
                "app.services.review_scheduler.load_revision_views",
                new=AsyncMock(return_value={1010: _make_revision_mock(10, 1)}),
            ),
        ):
            result = asyncio.run(get_today_review(db, user_id=1, subject_id=1))

        assert result["total_today"] == 1
        assert result["questions"][0]["subject_id"] == 1

    def test_limit(self):
        db = _make_mock_db()
        now = datetime.now(UTC)
        schedules = [
            _make_schedule_mock(
                id=i, question_id=10 + i, next_review_at=now - timedelta(days=i)
            )
            for i in range(1, 6)
        ]
        db.scalar.return_value = 5
        result = MagicMock()
        result.all.return_value = schedules[:3]
        db.scalars.return_value = result
        revisions = {
            1000 + q.question_id: _make_revision_mock(q.question_id)
            for q in schedules[:3]
        }
        with (
            patch(
                "app.services.review_scheduler._active_408_subject_ids",
                new=AsyncMock(return_value={1}),
            ),
            patch(
                "app.services.review_scheduler.load_revision_views",
                new=AsyncMock(return_value=revisions),
            ),
        ):
            result = asyncio.run(get_today_review(db, user_id=1, limit=3))

        assert len(result["questions"]) == 3

    def test_stem_from_string_content(self):
        db = _make_mock_db()
        now = datetime.now(UTC)
        schedules = [
            _make_schedule_mock(
                id=1, question_id=10, next_review_at=now - timedelta(days=1)
            )
        ]
        db.scalar.return_value = 1
        result = MagicMock()
        result.all.return_value = schedules
        db.scalars.return_value = result
        revision = _make_revision_mock(10)
        revision.content = "Plain text stem"
        with (
            patch(
                "app.services.review_scheduler._active_408_subject_ids",
                new=AsyncMock(return_value={1}),
            ),
            patch(
                "app.services.review_scheduler.load_revision_views",
                new=AsyncMock(return_value={1010: revision}),
            ),
        ):
            result = asyncio.run(get_today_review(db, user_id=1))

        assert result["questions"][0]["stem"] == "Plain text stem"


# ── submit_review Tests ──


class TestSubmitReview:
    def test_successful_submit(self):
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1,
            question_id=10,
            interval=5,
            ease_factor=2.5,
            repetitions=2,
            next_review_at=datetime.now(UTC) - timedelta(days=1),
        )
        # First execute: get schedule
        # commit/refresh don't need execute results
        db.scalar.side_effect = [None, schedule, 10, None]

        async def _run():
            return await submit_review(
                db,
                user_id=1,
                schedule_id=1,
                question_id=10,
                question_version_id=1010,
                occurrence_seq=0,
                rating=4,
                request_id="r1",
            )

        result = asyncio.run(_run())

        assert result["schedule_id"] == 1
        assert result["question_id"] == 10
        assert result["rating"] == 4
        assert result["is_correct"] is True
        assert result["interval_after"] > 0
        assert "next_review_at" in result
        assert "ease_factor_after" in result

    def test_schedule_not_found(self):
        db = _make_mock_db()
        db.scalar.side_effect = [None, None]

        with pytest.raises(ValueError, match="复习记录不存在"):
            asyncio.run(
                submit_review(
                    db,
                    user_id=1,
                    schedule_id=999,
                    question_id=10,
                    question_version_id=1010,
                    occurrence_seq=0,
                    rating=4,
                    request_id="r1",
                )
            )

    def test_invalid_rating(self):
        db = _make_mock_db()

        with pytest.raises(ValueError, match="评分必须在 0-5 之间"):
            asyncio.run(
                submit_review(
                    db,
                    user_id=1,
                    schedule_id=1,
                    question_id=10,
                    question_version_id=1010,
                    occurrence_seq=0,
                    rating=6,
                    request_id="r1",
                )
            )

    def test_wrong_answer_resets_schedule(self):
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1,
            question_id=10,
            interval=30,
            ease_factor=2.5,
            repetitions=5,
            next_review_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.scalar.side_effect = [None, schedule, 10, None]

        async def _run():
            return await submit_review(
                db,
                user_id=1,
                schedule_id=1,
                question_id=10,
                question_version_id=1010,
                occurrence_seq=0,
                rating=1,
                request_id="r1",
            )

        result = asyncio.run(_run())

        assert result["is_correct"] is False
        assert result["interval_after"] == 1  # Reset to 1 day

    def test_record_created(self):
        db = _make_mock_db()
        added_objects = []

        def _add(obj):
            added_objects.append(obj)

        db.add.side_effect = _add
        schedule = _make_schedule_mock(
            id=1,
            question_id=10,
            interval=5,
            ease_factor=2.5,
            repetitions=2,
            next_review_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.scalar.side_effect = [None, schedule, 10, None]

        asyncio.run(
            submit_review(
                db,
                user_id=1,
                schedule_id=1,
                question_id=10,
                question_version_id=1010,
                occurrence_seq=0,
                rating=4,
                request_id="r1",
            )
        )

        # Check that a ReviewRecord was added
        from app.models.review_scheduler import ReviewRecord

        records = [obj for obj in added_objects if isinstance(obj, ReviewRecord)]
        assert len(records) == 1
        assert records[0].rating == 4
        assert records[0].user_id == 1
        assert records[0].question_id == 10


# ── auto_schedule_wrong_question Tests ──


class TestAutoScheduleWrongQuestion:
    def test_creates_new_schedule(self):
        db = _make_mock_db()
        added_objects = []

        def _add(obj):
            added_objects.append(obj)

        db.add.side_effect = _add
        db.scalar.side_effect = [None, None]

        async def _run():
            return await auto_schedule_wrong_question(
                db, user_id=1, question_id=10, question_version_id=1010
            )

        with patch(
            "app.services.review_scheduler.load_revision_views",
            new=AsyncMock(return_value={1010: _make_revision_mock(10)}),
        ):
            asyncio.run(_run())

        from app.models.review_scheduler import ReviewSchedule

        schedules = [obj for obj in added_objects if isinstance(obj, ReviewSchedule)]
        assert len(schedules) == 1
        assert schedules[0].user_id == 1
        assert schedules[0].question_id == 10
        assert schedules[0].interval == 1
        assert schedules[0].ease_factor == 2.5
        assert schedules[0].repetitions == 0
        assert schedules[0].next_review_at is not None  # Immediate review

    def test_updates_existing_schedule(self):
        db = _make_mock_db()
        existing = _make_schedule_mock(
            id=1,
            question_id=10,
            interval=30,
            ease_factor=2.8,
            repetitions=10,
            next_review_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.scalar.side_effect = [existing, None]

        async def _run():
            return await auto_schedule_wrong_question(
                db, user_id=1, question_id=10, question_version_id=1010
            )

        with patch(
            "app.services.review_scheduler.load_revision_views",
            new=AsyncMock(return_value={1010: _make_revision_mock(10)}),
        ):
            asyncio.run(_run())

        # Should reset to difficult state
        assert existing.interval == 1
        assert existing.ease_factor == 2.5
        assert existing.repetitions == 0


# ── get_review_stats Tests ──


class TestReviewStats:
    def test_basic_stats(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 50},  # total_scheduled
            {"scalar": 5},  # total_reviewed_today
            {"scalar": 10},  # remaining_today
            {"scalar": 3},  # overdue
            {"one": (20, 16)},  # accuracy: 20 total, 16 correct
            {"all": []},  # by_subject scheduled
            {"all": []},  # by_subject reviewed
        )

        result = asyncio.run(get_review_stats(db, user_id=1))

        assert result["total_scheduled"] == 50
        assert result["total_reviewed_today"] == 5
        assert result["remaining_today"] == 10
        assert result["overdue"] == 3
        assert result["accuracy_last_7d"] == 0.8

    def test_empty_stats(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 0},
            {"scalar": 0},
            {"scalar": 0},
            {"scalar": 0},
            {"one": (0, 0)},
            {"all": []},
            {"all": []},
        )

        result = asyncio.run(get_review_stats(db, user_id=1))

        assert result["total_scheduled"] == 0
        assert result["accuracy_last_7d"] == 0.0

    def test_by_subject_stats(self):
        from app.models.admin import Subject

        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 30},
            {"scalar": 3},
            {"scalar": 8},
            {"scalar": 2},
            {"one": (15, 12)},
            {"all": [(1, 30, 8), (2, 20, 5)]},  # by_subject scheduled rows
            {"all": [(1, 3), (2, 1)]},  # by_subject reviewed rows
            {
                "scalars": [
                    Subject(id=1, code="math2", name="数学二", level=1, path="math2"),
                    Subject(id=2, code="english", name="英语", level=1, path="english"),
                ]
            },  # subjects query
        )

        result = asyncio.run(get_review_stats(db, user_id=1))

        assert "by_subject" in result
        by_code = {s["subject_id"]: s for s in result["by_subject"]}
        assert by_code[1]["subject_code"] == "math2"
        assert by_code[1]["scheduled"] == 30
        assert by_code[2]["subject_code"] == "english"
        assert by_code[2]["reviewed"] == 1


# ── get_review_history Tests ──


class TestReviewHistory:
    def test_returns_history(self):
        db = _make_mock_db()
        from app.models.review_scheduler import ReviewRecord

        records = [
            ReviewRecord(
                user_id=1,
                question_id=10,
                schedule_id=1,
                rating=4,
                interval_after=6,
                reviewed_at=datetime.now(UTC),
            ),
            ReviewRecord(
                user_id=1,
                question_id=11,
                schedule_id=2,
                rating=2,
                interval_after=1,
                reviewed_at=datetime.now(UTC) - timedelta(days=1),
            ),
        ]
        _mock_execute_sequence(
            db,
            {"scalar": 2},
            {"scalars": records},
        )

        result = asyncio.run(get_review_history(db, user_id=1))

        assert result["total"] == 2
        assert result["page"] == 1
        assert len(result["items"]) == 2
        assert result["items"][0]["rating"] == 4
        assert result["items"][1]["rating"] == 2

    def test_pagination(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 100},
            {"scalars": []},
        )

        result = asyncio.run(get_review_history(db, user_id=1, page=2, page_size=20))

        assert result["total"] == 100
        assert result["page"] == 2
        assert result["page_size"] == 20

    def test_empty_history(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 0},
            {"scalars": []},
        )

        result = asyncio.run(get_review_history(db, user_id=1))

        assert result["total"] == 0
        assert result["items"] == []
