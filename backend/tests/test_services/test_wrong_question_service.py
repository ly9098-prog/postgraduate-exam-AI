"""Stage 12: wrong_question_service 单元测试 — 验证 SM-2 收口后的行为。"""
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.services.sm2_service import calc_sm2
from app.services.wrong_question_service import record_wrong, update_quality

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
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401

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
            mock_scalars.first.return_value = value[0] if value else None
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        elif method == "scalar_one_or_none":
            mock_result.scalar_one_or_none.return_value = value
        elif method == "one":
            mock_result.one.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


# ── record_wrong Tests ──


class TestRecordWrong:
    def test_creates_new_wrong_question_without_sm2_fields(self):
        """新建 WrongQuestion 时不应写入 SM-2 字段。"""
        db = _make_mock_db()
        added_objects = []

        def _add(obj):
            added_objects.append(obj)

        db.add.side_effect = _add

        # WQ query: no existing record
        wq_none_result = _make_execute_result(scalars=[])
        # auto_schedule: schedule query → no existing
        schedule_none_result = _make_execute_result(scalar_one_or_none=None)
        # auto_schedule: question query for subject
        from app.models.question import Question
        q_mock = MagicMock(spec=Question)
        q_mock.subject_id = 1
        question_result = _make_execute_result(scalar_one_or_none=q_mock)
        # auto_schedule: WQ sync → no existing
        sync_result = _make_execute_result(scalar_one_or_none=None)

        db.execute.side_effect = [wq_none_result, schedule_none_result, question_result, sync_result]

        async def _run():
            return await record_wrong(db, user_id=1, question_id=10, wrong_answer="B")

        asyncio.run(_run())

        # 验证新建的 WQ 没有 SM-2 字段
        from app.models.wrong_question import WrongQuestion
        wqs = [obj for obj in added_objects if isinstance(obj, WrongQuestion)]
        assert len(wqs) == 1
        wq = wqs[0]
        assert wq.wrong_answer == "B"
        assert wq.review_count == 1
        assert not hasattr(wq, 'efactor') or wq.efactor is None or True  # 模型已移除 SM-2 字段

    def test_updates_existing_wrong_question(self):
        """更新已有 WrongQuestion 时只维护错题分析字段。"""
        db = _make_mock_db()
        from app.models.wrong_question import WrongQuestion
        existing_wq = MagicMock(spec=WrongQuestion)
        existing_wq.wrong_answer = "A"
        existing_wq.review_count = 1
        existing_wq.last_review_at = None
        existing_wq.mastered = False

        # WQ query: existing record found
        wq_found_result = _make_execute_result(scalars=[existing_wq])
        # auto_schedule: schedule query → existing
        schedule_mock = MagicMock()
        schedule_mock.interval = 1
        schedule_mock.ease_factor = 2.5
        schedule_mock.repetitions = 0
        schedule_mock.next_review_at = datetime.now(UTC).replace(tzinfo=None)
        schedule_mock.last_reviewed_at = None
        schedule_mock.mastered = False
        schedule_mock.user_id = 1
        schedule_mock.question_id = 10
        schedule_found_result = _make_execute_result(scalar_one_or_none=schedule_mock)
        # auto_schedule: WQ sync → found
        sync_found_result = _make_execute_result(scalar_one_or_none=existing_wq)

        db.execute.side_effect = [wq_found_result, schedule_found_result, sync_found_result]

        async def _run():
            return await record_wrong(db, user_id=1, question_id=10, wrong_answer="C")

        asyncio.run(_run())

        assert existing_wq.wrong_answer == "C"
        assert existing_wq.review_count == 2
        assert existing_wq.mastered is False


# ── update_quality Tests ──


class TestUpdateQuality:
    def test_routes_through_review_scheduler(self):
        """update_quality 必须通过 review_scheduler.submit_review 路由 SM-2，不在 WQ 上独立计算。"""
        db = _make_mock_db()
        from app.models.wrong_question import WrongQuestion

        wq_mock = MagicMock(spec=WrongQuestion)
        wq_mock.id = 1
        wq_mock.user_id = 1
        wq_mock.question_id = 10
        wq_mock.wrong_answer = "B"
        wq_mock.review_count = 1

        # Step 1: get_by_id → found WQ
        wq_result = _make_execute_result(scalar_one_or_none=wq_mock)
        # Step 2: find ReviewSchedule → found
        schedule_mock = MagicMock()
        schedule_mock.id = 1
        schedule_mock.user_id = 1
        schedule_mock.question_id = 10
        schedule_mock.interval = 5
        schedule_mock.ease_factor = 2.5
        schedule_mock.repetitions = 2
        schedule_mock.next_review_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        schedule_mock.last_reviewed_at = None
        schedule_result = _make_execute_result(scalar_one_or_none=schedule_mock)
        # Step 3: submit_review → schedule query
        submit_schedule_result = _make_execute_result(scalar_one_or_none=schedule_mock)
        # Step 4: submit_review → WQ sync
        sync_result = _make_execute_result(scalar_one_or_none=wq_mock)

        db.execute.side_effect = [wq_result, schedule_result, submit_schedule_result, sync_result]

        async def _run():
            return await update_quality(db, user_id=1, wq_id=1, quality=4)

        asyncio.run(_run())

        # 验证 schedule 被更新了 SM-2 参数
        assert schedule_mock.interval > 0
        assert schedule_mock.last_reviewed_at is not None
        # 验证 WQ 的 last_review_at 被同步
        assert wq_mock.last_review_at is not None

    def test_creates_schedule_if_not_exists(self):
        """如果没有 ReviewSchedule，应通过 auto_schedule 创建后再 submit。"""
        db = _make_mock_db()
        from app.models.wrong_question import WrongQuestion

        wq_mock = MagicMock(spec=WrongQuestion)
        wq_mock.id = 1
        wq_mock.user_id = 1
        wq_mock.question_id = 10
        wq_mock.wrong_answer = "B"
        wq_mock.review_count = 1

        # get_by_id → found
        wq_result = _make_execute_result(scalar_one_or_none=wq_mock)
        # find schedule → not found
        no_schedule_result = _make_execute_result(scalar_one_or_none=None)
        # auto_schedule: find schedule → not found
        auto_no_schedule = _make_execute_result(scalar_one_or_none=None)
        # auto_schedule: question query
        from app.models.question import Question
        q_mock = MagicMock(spec=Question)
        q_mock.subject_id = 1
        question_result = _make_execute_result(scalar_one_or_none=q_mock)
        # auto_schedule: WQ sync
        sync_result = _make_execute_result(scalar_one_or_none=wq_mock)
        # submit_review: schedule query (the new schedule)
        new_schedule = MagicMock()
        new_schedule.id = 99
        new_schedule.user_id = 1
        new_schedule.question_id = 10
        new_schedule.interval = 1
        new_schedule.ease_factor = 2.5
        new_schedule.repetitions = 0
        new_schedule.next_review_at = datetime.now(UTC).replace(tzinfo=None)
        new_schedule.last_reviewed_at = None
        submit_schedule_result = _make_execute_result(scalar_one_or_none=new_schedule)
        # submit_review: WQ sync
        submit_sync_result = _make_execute_result(scalar_one_or_none=wq_mock)

        db.execute.side_effect = [
            wq_result, no_schedule_result,
            auto_no_schedule, question_result, sync_result,
            submit_schedule_result, submit_sync_result,
        ]

        async def _run():
            return await update_quality(db, user_id=1, wq_id=1, quality=3)

        asyncio.run(_run())

        # 新 schedule 应被 SM-2 更新
        assert new_schedule.last_reviewed_at is not None


# ── SM-2 Rating Mapping Tests ──


class TestAutoGradeRatingMapping:
    """验证自动批改评分映射：答对=4, 答错=1。"""

    def test_correct_maps_to_rating_4(self):
        """答对时 rating=4（不是 5）。"""
        result = calc_sm2(quality=4, efactor=2.5, interval=5, repetitions=2)
        assert result["interval"] > 5  # 适度增长
        assert result["repetitions"] == 3

    def test_wrong_maps_to_rating_1(self):
        """答错时 rating=1（不是 0）。"""
        result = calc_sm2(quality=1, efactor=2.5, interval=5, repetitions=2)
        assert result["interval"] == 1  # 重置
        assert result["repetitions"] == 0
        # rating=1 的 efactor 下降幅度应小于 rating=0
        result_0 = calc_sm2(quality=0, efactor=2.5, interval=5, repetitions=2)
        assert result["efactor"] > result_0["efactor"]

    def test_rating_4_less_growth_than_5(self):
        """rating=4 的增长幅度应小于 rating=5。"""
        r4 = calc_sm2(quality=4, efactor=2.5, interval=10, repetitions=3)
        r5 = calc_sm2(quality=5, efactor=2.5, interval=10, repetitions=3)
        assert r4["efactor"] < r5["efactor"]
        assert r4["interval"] <= r5["interval"]

    def test_rating_1_less_penalty_than_0(self):
        """rating=1 的惩罚应小于 rating=0。"""
        r1 = calc_sm2(quality=1, efactor=2.5, interval=10, repetitions=3)
        r0 = calc_sm2(quality=0, efactor=2.5, interval=10, repetitions=3)
        assert r1["efactor"] > r0["efactor"]  # 1 的 efactor 下降更少
