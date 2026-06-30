"""Stage 12: SM-2 复习调度系统 — 单元测试。"""
import asyncio
from datetime import timezone, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.review_scheduler import (
    auto_schedule_wrong_question,
    get_review_history,
    get_review_stats,
    get_today_review,
    submit_review,
    batch_submit_review,
)
from app.services.sm2_service import calc_sm2


# ── Helpers ──


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
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


def _make_schedule_mock(id=1, user_id=1, question_id=10, subject="math2",
                        interval=5, ease_factor=2.5, repetitions=2,
                        next_review_at=None):
    s = MagicMock()
    s.id = id
    s.user_id = user_id
    s.question_id = question_id
    s.subject = subject
    s.interval = interval
    s.ease_factor = ease_factor
    s.repetitions = repetitions
    s.next_review_at = next_review_at or datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    s.last_reviewed_at = None
    s.mastered = False
    return s


def _make_question_mock(id=10, subject="math2", question_type="single_choice",
                        content=None, options=None, answer="A", analysis="test"):
    q = MagicMock()
    q.id = id
    q.subject_id = 1
    subj_ref = MagicMock()
    subj_ref.code = subject
    q.subject_ref = subj_ref
    q.question_type = question_type
    q.content = content or {"text": "Test question stem"}
    q.options = options or {"A": "option a", "B": "option b"}
    q.answer = answer
    q.analysis = analysis
    return q


# ── SM-2 Algorithm Tests (pure function) ──


class TestSM2Algorithm:
    """测试核心 SM-2 算法（复用 sm2_service.calc_sm2）。"""

    def test_rating_5_max_growth(self):
        result = calc_sm2(quality=5, efactor=2.5, interval=10, repetitions=3)
        # 稳定四舍五入: floor(10 * 2.5 + 0.5) = floor(25.5) = 25
        assert result["interval"] == 25
        assert result["efactor"] >= 2.5  # EF should increase for quality=5
        assert result["repetitions"] == 4

    def test_rating_4(self):
        result = calc_sm2(quality=4, efactor=2.5, interval=6, repetitions=2)
        # floor(6 * 2.5 + 0.5) = floor(15.5) = 15
        assert result["interval"] == 15
        assert result["repetitions"] == 3

    def test_rating_3_pass_threshold(self):
        result = calc_sm2(quality=3, interval=6, repetitions=2)
        assert result["interval"] == 15  # floor(6*2.5 + 0.5)
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
        assert result["interval"] == 15  # floor(6 * 2.5 + 0.5)
        assert result["repetitions"] == 3

    def test_repetitions_reset_on_wrong(self):
        result = calc_sm2(quality=1, interval=30, repetitions=10)
        assert result["repetitions"] == 0

    def test_ef_decrease_on_low_rating(self):
        result_before = calc_sm2(quality=5, efactor=2.5, interval=1, repetitions=1)
        ef_after_good = result_before["efactor"]

        result_after = calc_sm2(quality=1, efactor=ef_after_good, interval=1, repetitions=0)
        assert result_after["efactor"] < ef_after_good

    def test_invalid_rating_raises(self):
        with pytest.raises(ValueError):
            calc_sm2(quality=6)
        with pytest.raises(ValueError):
            calc_sm2(quality=-1)

    def test_next_review_date_is_future(self):
        result = calc_sm2(quality=4, interval=6, repetitions=2)
        assert result["next_review_date"] >= date.today()

    def test_stable_rounding_bankers_case(self):
        """验证使用 math.floor(x+0.5) 而非 round()（银行家舍入）。
        round(22.5) == 22（银行家舍入），而 floor(22.5 + 0.5) == 23（期望）。"""
        result = calc_sm2(quality=4, efactor=2.5, interval=9, repetitions=2)
        # interval * efactor = 22.5
        assert result["interval"] == 23  # 稳定四舍五入

    def test_interval_min_1(self):
        """即使计算结果为 0，interval 也不应低于 1。"""
        result = calc_sm2(quality=4, efactor=1.3, interval=0, repetitions=2)
        assert result["interval"] >= 1

    def test_rating_5_ef_2_7_interval_6_repetitions_2(self):
        """特定边界: quality=5, efactor=2.7, interval=6, repetitions=2
        => interval=floor(6*2.7+0.5)=16, repetitions=3, efactor=2.8"""
        result = calc_sm2(quality=5, efactor=2.7, interval=6, repetitions=2)
        assert result["interval"] == 16  # floor(6*2.7+0.5) = 16
        assert result["repetitions"] == 3
        assert result["efactor"] == 2.8  # 2.7 + 0.1


# ── get_today_review Tests ──


class TestGetTodayReview:
    def test_returns_due_reviews(self):
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        schedules = [
            _make_schedule_mock(id=1, question_id=10, next_review_at=now - timedelta(days=2)),
            _make_schedule_mock(id=2, question_id=11, next_review_at=now - timedelta(hours=1)),
        ]
        questions = [
            _make_question_mock(id=10),
            _make_question_mock(id=11),
        ]
        _mock_execute_sequence(
            db,
            {"scalar": 2},           # count
            {"scalars": schedules},   # schedules query
            {"scalars": questions},   # questions query
        )

        result = asyncio.run(get_today_review(db, user_id=1))

        assert result["total_today"] == 2
        assert len(result["questions"]) == 2
        assert result["questions"][0]["schedule_id"] == 1
        assert result["questions"][0]["question_id"] == 10
        assert "answer" not in result["questions"][0]  # 不返回答案

    def test_empty_when_no_due(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 0},
            {"scalars": []},
            {"scalars": []},
        )

        result = asyncio.run(get_today_review(db, user_id=1))

        assert result["total_today"] == 0
        assert result["questions"] == []

    def test_subject_filter(self):
        """subject 筛选在 SQL 层完成，返回仅包含目标 subject 的复习题。"""
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # SQL 层已按 subject 过滤，只返回 math2 的记录
        math_schedule = _make_schedule_mock(id=1, question_id=10, subject="math2", next_review_at=now - timedelta(days=1))
        math_q = _make_question_mock(id=10, subject="math2")
        _mock_execute_sequence(
            db,
            {"scalar": 1},          # count 已按 subject 过滤
            {"scalars": [math_schedule]},  # schedules 已按 subject 过滤
            {"scalars": [math_q]},
        )

        result = asyncio.run(get_today_review(db, user_id=1, subject="math2"))

        assert result["total_today"] == 1
        assert len(result["questions"]) == 1
        assert result["questions"][0]["subject"] == "math2"

    def test_subject_filter_with_limit_does_not_leak(self):
        """验证 subject 筛选在 SQL limit 之前执行，不会因 limit 先截断而漏题。"""
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # 即使总共有 5 条待复习且 limit=3，SQL 层只返回 2 条 math2 的
        math_schedules = [
            _make_schedule_mock(id=i, question_id=10 + i, subject="math2",
                                next_review_at=now - timedelta(days=2 - i))
            for i in range(2)
        ]
        math_questions = [_make_question_mock(id=10 + i, subject="math2") for i in range(2)]
        _mock_execute_sequence(
            db,
            {"scalar": 2},          # SQL count 只统计 math2
            {"scalars": math_schedules},  # 只返回 math2 的 schedules
            {"scalars": math_questions},
        )

        result = asyncio.run(get_today_review(db, user_id=1, subject="math2", limit=3))

        assert result["total_today"] == 2
        assert len(result["questions"]) == 2
        for q in result["questions"]:
            assert q["subject"] == "math2"

    def test_limit(self):
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        schedules = [
            _make_schedule_mock(id=i, question_id=10 + i, next_review_at=now - timedelta(days=i))
            for i in range(1, 6)
        ]
        questions = [_make_question_mock(id=10 + i) for i in range(1, 6)]
        _mock_execute_sequence(
            db,
            {"scalar": 5},
            {"scalars": schedules[:3]},   # limit=3
            {"scalars": questions},
        )

        result = asyncio.run(get_today_review(db, user_id=1, limit=3))

        assert len(result["questions"]) == 3

    def test_stem_from_string_content(self):
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        schedules = [_make_schedule_mock(id=1, question_id=10, next_review_at=now - timedelta(days=1))]
        q = _make_question_mock(id=10, content="Plain text stem")
        _mock_execute_sequence(
            db,
            {"scalar": 1},
            {"scalars": schedules},
            {"scalars": [q]},
        )

        result = asyncio.run(get_today_review(db, user_id=1))

        assert result["questions"][0]["stem"] == "Plain text stem"


# ── submit_review Tests ──


class TestSubmitReview:
    def test_successful_submit(self):
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1, question_id=10, interval=5, ease_factor=2.5, repetitions=2,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        # schedule query + WQ sync query
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),
            _make_execute_result(scalar_one_or_none=None),
        ]

        async def _run():
            return await submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=4)

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
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with pytest.raises(ValueError, match="复习记录不存在"):
            asyncio.run(submit_review(db, user_id=1, schedule_id=999, question_id=10, rating=4))

    def test_invalid_rating(self):
        db = _make_mock_db()

        with pytest.raises(ValueError, match="评分必须在 0-5 之间"):
            asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=6))

    def test_wrong_answer_resets_schedule(self):
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1, question_id=10, interval=30, ease_factor=2.5, repetitions=5,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),
            _make_execute_result(scalar_one_or_none=None),
        ]

        async def _run():
            return await submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=1)

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
            id=1, question_id=10, interval=5, ease_factor=2.5, repetitions=2,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),
            _make_execute_result(scalar_one_or_none=None),
        ]

        asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=4))

        # Check that a ReviewRecord was added
        from app.models.review_scheduler import ReviewRecord
        records = [obj for obj in added_objects if isinstance(obj, ReviewRecord)]
        assert len(records) == 1
        assert records[0].rating == 4
        assert records[0].user_id == 1
        assert records[0].question_id == 10

    def test_auto_grade_correct_rating_4_behavior(self):
        """自动批改答对时 rating=4（非 5），验证 SM-2 行为。"""
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1, question_id=10, interval=5, ease_factor=2.5, repetitions=2,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),
            _make_execute_result(scalar_one_or_none=None),
        ]

        # 模拟 grade-submit 使用 rating=4（答对时的新映射值）
        result = asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=4))

        assert result["is_correct"] is True
        # rating=4 时 SM-2 应有适度增长（不是 max growth 的 5）
        calc_4 = calc_sm2(quality=4, efactor=2.5, interval=5, repetitions=2)
        calc_5 = calc_sm2(quality=5, efactor=2.5, interval=5, repetitions=2)
        assert calc_4["efactor"] < calc_5["efactor"]  # 4 的增幅小于 5

    def test_auto_grade_wrong_rating_1_behavior(self):
        """自动批改答错时 rating=1（非 0），验证 SM-2 行为。"""
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1, question_id=10, interval=5, ease_factor=2.5, repetitions=2,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),
            _make_execute_result(scalar_one_or_none=None),
        ]

        # 模拟 grade-submit 使用 rating=1（答错时的新映射值）
        result = asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=1))

        assert result["is_correct"] is False
        assert result["interval_after"] == 1  # 重置为 1 天
        # rating=1 时 SM-2 的 ease_factor 下降幅度应小于 rating=0
        calc_1 = calc_sm2(quality=1, efactor=2.5, interval=5, repetitions=2)
        calc_0 = calc_sm2(quality=0, efactor=2.5, interval=5, repetitions=2)
        assert calc_1["efactor"] > calc_0["efactor"]  # 1 的下降幅度小于 0

    def test_invalid_rating_rejected(self):
        """评分超出 0-5 范围应被拒绝。"""
        db = _make_mock_db()
        with pytest.raises(ValueError):
            asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=6))
        with pytest.raises(ValueError):
            asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=-1))

    def test_rating_0_accepted_as_valid(self):
        """rating=0 是合法 SM-2 评分（完全不会），不应被拒绝。"""
        db = _make_mock_db()
        schedule = _make_schedule_mock(
            id=1, question_id=10, interval=30, ease_factor=2.5, repetitions=5,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),   # schedule query
            _make_execute_result(scalar_one_or_none=None),       # WQ sync (no record)
        ]

        result = asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=0))

        assert result["is_correct"] is False  # rating < 3
        assert result["interval_after"] == 1  # reset to 1 day
        assert result["rating"] == 0

    def test_syncs_wrong_question_after_submit_review(self):
        """submit_review 后 WrongQuestion.last_review_at 应与 ReviewSchedule 同步。"""
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        schedule = _make_schedule_mock(
            id=1, question_id=10, interval=5, ease_factor=2.5, repetitions=2,
            next_review_at=now - timedelta(days=1),
        )
        schedule.last_reviewed_at = now
        from app.models.wrong_question import WrongQuestion
        wq_mock = MagicMock(spec=WrongQuestion)
        wq_mock.last_review_at = None

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=schedule),   # schedule query
            _make_execute_result(scalar_one_or_none=wq_mock),    # WQ found → sync
        ]

        asyncio.run(submit_review(db, user_id=1, schedule_id=1, question_id=10, rating=4))

        assert wq_mock.last_review_at == schedule.last_reviewed_at


# ── batch_submit_review Tests ──


class TestBatchSubmitReview:
    def test_batch_success(self):
        db = _make_mock_db()
        schedule_mocks = [
            _make_schedule_mock(id=1, question_id=10),
            _make_schedule_mock(id=2, question_id=11),
        ]

        # 2 reviews × 2 executes each (schedule query + WQ sync)
        execute_results = [
            schedule_mocks[0], None,  # submit_review #1: schedule, WQ
            schedule_mocks[1], None,  # submit_review #2: schedule, WQ
        ]
        call_index = 0

        def _execute_side_effect(*args, **kwargs):
            nonlocal call_index
            idx = call_index
            call_index += 1
            if idx < len(execute_results):
                return _make_execute_result(scalar_one_or_none=execute_results[idx])
            return _make_execute_result(scalar_one_or_none=None)

        db.execute.side_effect = _execute_side_effect

        async def _run():
            return await batch_submit_review(db, user_id=1, reviews=[
                {"schedule_id": 1, "question_id": 10, "rating": 4},
                {"schedule_id": 2, "question_id": 11, "rating": 3},
            ])

        result = asyncio.run(_run())

        assert result["total"] == 2
        assert len(result["results"]) == 2

    def test_batch_continues_on_error(self):
        """批量提交时，单个失败不影响其他。错误被记录在 results 中。"""
        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        async def _run():
            return await batch_submit_review(db, user_id=1, reviews=[
                {"schedule_id": 999, "question_id": 10, "rating": 4},
            ])

        result = asyncio.run(_run())

        assert result["total"] == 1
        assert result["results"][0].get("error") is not None
        assert result["results"][0]["schedule_id"] == 999


# ── auto_schedule_wrong_question Tests ──


class TestAutoScheduleWrongQuestion:
    def test_creates_new_schedule(self):
        db = _make_mock_db()
        added_objects = []

        def _add(obj):
            added_objects.append(obj)

        db.add.side_effect = _add
        _mock_execute_sequence(
            db,
            {"scalar_one_or_none": None},         # ReviewSchedule query
            {"scalar_one_or_none": None},         # Question query (for subject — new schedule)
            {"scalar_one_or_none": None},         # WrongQuestion sync (no existing WrongQuestion)
        )

        async def _run():
            return await auto_schedule_wrong_question(db, user_id=1, question_id=10)

        result = asyncio.run(_run())

        from app.models.review_scheduler import ReviewSchedule
        schedules = [obj for obj in added_objects if isinstance(obj, ReviewSchedule)]
        assert len(schedules) == 1
        assert schedules[0].user_id == 1
        assert schedules[0].question_id == 10
        assert schedules[0].interval == 1
        assert schedules[0].ease_factor == 2.5
        assert schedules[0].repetitions == 0
        assert schedules[0].next_review_at is not None  # Immediate review

    def test_updates_existing_schedule_resets_for_wrong(self):
        """已有 ReviewSchedule 再次做错，应重置为困难状态：interval=1, efactor=2.5, repetitions=0。"""
        db = _make_mock_db()
        existing = _make_schedule_mock(
            id=1, question_id=10, interval=30, ease_factor=2.8, repetitions=10,
            next_review_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
        )
        _mock_execute_sequence(
            db,
            {"scalar_one_or_none": existing},         # ReviewSchedule query
            {"scalar_one_or_none": None},             # WrongQuestion sync (no record)
        )

        async def _run():
            return await auto_schedule_wrong_question(db, user_id=1, question_id=10)

        result = asyncio.run(_run())

        # 做错后重置为初始困难状态
        assert existing.interval == 1
        assert existing.repetitions == 0
        assert existing.ease_factor == 2.5
        assert existing.mastered is False

    def test_syncs_wrong_question_after_auto_schedule(self):
        """auto_schedule_wrong_question 后 WrongQuestion.last_review_at 应与 ReviewSchedule 同步。"""
        db = _make_mock_db()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        existing = _make_schedule_mock(
            id=1, question_id=10, interval=30, ease_factor=2.8, repetitions=10,
            next_review_at=now + timedelta(days=30),
        )
        existing.last_reviewed_at = now
        from app.models.wrong_question import WrongQuestion
        wq_mock = MagicMock(spec=WrongQuestion)
        wq_mock.last_review_at = None

        _mock_execute_sequence(
            db,
            {"scalar_one_or_none": existing},         # ReviewSchedule query
            {"scalar_one_or_none": wq_mock},          # WrongQuestion found
        )

        asyncio.run(auto_schedule_wrong_question(db, user_id=1, question_id=10))

        assert wq_mock.last_review_at == existing.last_reviewed_at


# ── get_review_stats Tests ──


class TestReviewStats:
    def test_basic_stats(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 50},           # total_scheduled
            {"scalar": 5},            # total_reviewed_today
            {"scalar": 10},           # remaining_today
            {"scalar": 3},            # overdue
            {"one": (20, 16)},        # accuracy: 20 total, 16 correct
            {"scalars": []},          # by_subject scheduled
            {"scalars": []},          # by_subject reviewed
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
            {"scalars": []},
            {"scalars": []},
        )

        result = asyncio.run(get_review_stats(db, user_id=1))

        assert result["total_scheduled"] == 0
        assert result["accuracy_last_7d"] == 0.0

    def test_by_subject_stats(self):
        db = _make_mock_db()
        _mock_execute_sequence(
            db,
            {"scalar": 30},
            {"scalar": 3},
            {"scalar": 8},
            {"scalar": 2},
            {"one": (15, 12)},
            {"scalars": [
                MagicMock(**{"__getitem__": lambda s, k: {"math2": (0, 30, 8), "english": (1, 20, 5)}[s][k]})
            ]},
            {"scalars": [MagicMock(**{"__getitem__": lambda s, k: {"math2": (0, 3), "english": (1, 1)}[s][k]})]},
        )

        result = asyncio.run(get_review_stats(db, user_id=1))

        # With this mock setup, subject stats will be populated
        assert "by_subject" in result


# ── get_review_history Tests ──


class TestReviewHistory:
    def test_returns_history(self):
        db = _make_mock_db()
        from app.models.review_scheduler import ReviewRecord

        records = [
            ReviewRecord(user_id=1, question_id=10, schedule_id=1, rating=4,
                        interval_after=6, reviewed_at=datetime.now(timezone.utc).replace(tzinfo=None)),
            ReviewRecord(user_id=1, question_id=11, schedule_id=2, rating=2,
                        interval_after=1, reviewed_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)),
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
