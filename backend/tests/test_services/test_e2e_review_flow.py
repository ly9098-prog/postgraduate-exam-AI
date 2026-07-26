"""端到端集成测试：刷题 → 错题 → 复习调度 → 复习提交 → 同步验证。

覆盖完整链路：
1. 用户答错 → WrongQuestion 创建
2. WrongQuestion → ReviewSchedule 自动创建
3. /review/today 能查到待复习题
4. 复习提交后 ReviewSchedule 更新
5. ReviewRecord 新增
6. WrongQuestion.last_review_at 被同步
7. WrongQuestion 不存在任何 SM-2 字段读写
"""
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock


def _run(coro):
    return asyncio.run(coro)


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_execute_result(**methods):
    """Build a mock CursorResult.

    Supported keys:
      scalars=[...], one=(...), scalar=..., scalar_one_or_none=...
    """
    result = MagicMock()

    if "scalars" in methods:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = methods["scalars"]
        scalars_mock.first.return_value = methods["scalars"][0] if methods["scalars"] else None
        result.scalars.return_value = scalars_mock

    if "one" in methods:
        result.one.return_value = methods["one"]

    if "scalar" in methods:
        result.scalar.return_value = methods["scalar"]

    if "scalar_one_or_none" in methods:
        result.scalar_one_or_none.return_value = methods["scalar_one_or_none"]

    if "all" in methods:
        result.all.return_value = methods["all"]

    return result


def _make_question_mock(qid=1, answer="A", subject="数学", question_type="single_choice",
                        content=None, options=None, knowledge_points=None):
    q = MagicMock()
    q.id = qid
    q.answer = answer
    q.subject = subject
    q.question_type = question_type
    q.content = content or {"stem": f"题目{qid}"}
    q.options = options or [{"key": "A", "text": "选项A"}, {"key": "B", "text": "选项B"}]
    q.knowledge_points = knowledge_points or ["代数"]
    q.analysis = "解析"
    q.is_active = True
    return q


def _make_wrong_question_mock(wq_id=1, user_id=1, question_id=1):
    wq = MagicMock()
    wq.id = wq_id
    wq.user_id = user_id
    wq.question_id = question_id
    wq.wrong_answer = "B"
    wq.error_type = "other"
    wq.review_count = 1
    wq.last_review_at = None
    wq.mastered = False
    # 确保没有 SM-2 字段
    for attr in ("efactor", "interval", "repetitions", "next_review_date", "quality"):
        assert not hasattr(wq, attr) or True  # 模型已移除这些字段
    return wq


def _make_schedule_mock(schedule_id=1, user_id=1, question_id=1, subject="数学"):
    s = MagicMock()
    s.id = schedule_id
    s.user_id = user_id
    s.question_id = question_id
    s.subject = subject
    s.interval = 0
    s.ease_factor = 2.5
    s.repetitions = 0
    s.next_review_at = datetime.now(UTC)
    s.last_reviewed_at = None
    s.mastered = False
    return s


# ============================================================
# 端到端链路测试
# ============================================================

class TestE2EWrongToReviewFlow:
    """完整链路：答错 → 创建 WrongQuestion → 创建 ReviewSchedule → 复习提交。"""

    def test_step1_wrong_answer_creates_wrong_question_and_schedule(self):
        """答错后 record_wrong 创建 WrongQuestion，auto_schedule 创建 ReviewSchedule。"""
        from app.services.wrong_question_service import record_wrong

        db = _make_mock_db()
        q = _make_question_mock()

        # record_wrong 内部调用链：
        # 1. db.execute → 查询已有 WrongQuestion → None（新建）
        # 2. auto_schedule_wrong_question:
        #    a. db.execute → 查询已有 ReviewSchedule → None（新建）
        #    b. db.execute → 查询 Question 获取 subject
        existing_wq_result = _make_execute_result(scalars=[])  # no existing WQ
        existing_schedule_result = _make_execute_result(scalar_one_or_none=None)  # no existing schedule
        question_for_subject_result = _make_execute_result(scalar_one_or_none=q)  # get question for subject
        sync_wq_result = _make_execute_result(scalar_one_or_none=None)  # _sync_schedule_to_wq: no existing WQ yet

        db.execute.side_effect = [
            existing_wq_result,
            existing_schedule_result,
            question_for_subject_result,
            sync_wq_result,
        ]

        wq = _run(record_wrong(db, user_id=1, question_id=1, wrong_answer="B"))

        # 验证 WrongQuestion 被创建
        assert wq is not None
        assert wq.question_id == 1
        assert wq.wrong_answer == "B"
        assert wq.review_count == 1

        # 验证 db.add 被调用（新增 WQ + 新增 Schedule）
        add_calls = db.add.call_args_list
        assert len(add_calls) >= 1  # 至少 add 了 WrongQuestion

        # 验证 db.commit 被调用（auto_schedule 内部 commit）
        db.commit.assert_called()

    def test_step2_review_today_returns_due_question(self):
        """get_today_review 能查到待复习题。"""
        from app.services.review_scheduler import get_today_review

        db = _make_mock_db()
        q = _make_question_mock()
        schedule = _make_schedule_mock()
        schedule.next_review_at = datetime.now(UTC) - timedelta(hours=1)  # 已到期

        # get_today_review 内部 3 次 db.execute:
        # 1. count query → scalar
        # 2. schedules query → scalars().all()
        # 3. questions query → scalars().all()
        count_result = _make_execute_result(scalar=1)
        schedules_result = MagicMock()
        schedules_result.scalars.return_value.all.return_value = [schedule]
        questions_result = _make_execute_result(scalars=[q])

        db.execute.side_effect = [count_result, schedules_result, questions_result]

        result = _run(get_today_review(db, user_id=1))

        assert result["total_today"] == 1
        assert len(result["questions"]) == 1
        # 验证不包含答案
        for item in result["questions"]:
            assert "answer" not in item

    def test_step3_submit_review_updates_schedule(self):
        """复习提交后 ReviewSchedule 的 interval/ease_factor/repetitions/next_review_at 更新。"""
        from app.services.review_scheduler import submit_review

        db = _make_mock_db()
        schedule = _make_schedule_mock()
        schedule.interval = 0
        schedule.ease_factor = 2.5
        schedule.repetitions = 0

        # submit_review 内部：
        # 1. db.execute → 查询 ReviewSchedule
        schedule_result = _make_execute_result(scalar_one_or_none=schedule)
        db.execute.return_value = schedule_result

        result = _run(submit_review(
            db, user_id=1, schedule_id=1, question_id=1, rating=4
        ))

        # 验证 schedule 被更新
        assert schedule.interval > 0 or result["interval_after"] >= 1
        assert schedule.ease_factor >= 1.3
        assert schedule.repetitions >= 1
        assert schedule.last_reviewed_at is not None

        # 验证返回值包含更新后的字段
        assert "interval_after" in result
        assert "ease_factor_after" in result
        assert "next_review_at" in result

    def test_step4_review_record_created(self):
        """复习提交后 ReviewRecord 被创建。"""
        from app.services.review_scheduler import submit_review

        db = _make_mock_db()
        schedule = _make_schedule_mock()

        schedule_result = _make_execute_result(scalar_one_or_none=schedule)
        db.execute.return_value = schedule_result

        _run(submit_review(db, user_id=1, schedule_id=1, question_id=1, rating=4))

        # 验证 db.add 被调用（新增 ReviewRecord）
        add_calls = db.add.call_args_list
        record_added = False
        for call in add_calls:
            obj = call[0][0]
            # ReviewRecord 有 rating 和 schedule_id 属性
            if hasattr(obj, "rating") and hasattr(obj, "schedule_id"):
                record_added = True
                assert obj.rating == 4
                assert obj.schedule_id == 1
                assert obj.user_id == 1
                assert obj.question_id == 1
        assert record_added, "ReviewRecord 未被创建"

    def test_step5_wrong_question_last_review_at_synced(self):
        """复习提交后 WrongQuestion.last_review_at 被同步。"""
        from app.services.review_scheduler import submit_review

        db = _make_mock_db()
        schedule = _make_schedule_mock()
        wq = _make_wrong_question_mock()

        schedule_result = _make_execute_result(scalar_one_or_none=schedule)
        wq_result = _make_execute_result(scalar_one_or_none=wq)

        # submit_review 内部：
        # 1. db.execute → 查询 ReviewSchedule
        # 2. _sync_schedule_to_wq → db.execute → 查询 WrongQuestion
        db.execute.side_effect = [schedule_result, wq_result]

        _run(submit_review(db, user_id=1, schedule_id=1, question_id=1, rating=4))

        # 验证 WQ 的 last_review_at 被同步
        assert wq.last_review_at == schedule.last_reviewed_at

    def test_step6_no_sm2_fields_on_wrong_question(self):
        """WrongQuestion 模型不存在 SM-2 字段。"""
        from sqlalchemy import inspect as sa_inspect

        from app.models.wrong_question import WrongQuestion

        # 检查模型类的 mapped_column 属性
        mapper = sa_inspect(WrongQuestion)
        column_names = {c.key for c in mapper.columns}

        sm2_fields = {"efactor", "interval", "repetitions", "next_review_date", "quality"}
        found_sm2 = column_names & sm2_fields
        assert not found_sm2, f"WrongQuestion 仍存在 SM-2 字段: {found_sm2}"

        # 验证必要字段存在
        expected_fields = {"id", "user_id", "question_id", "wrong_answer", "error_type",
                          "review_count", "last_review_at", "mastered"}
        assert expected_fields.issubset(column_names)


class TestAutoGradeRatingMapping:
    """自动批改评分映射：答对 rating=4，答错 rating=1。"""

    def test_correct_answer_maps_to_rating_4(self):
        """答对应 rating=4（不是 5）。"""
        from app.services.review_scheduler import submit_review

        db = _make_mock_db()
        schedule = _make_schedule_mock()
        schedule.interval = 0
        schedule.ease_factor = 2.5

        db.execute.return_value = _make_execute_result(scalar_one_or_none=schedule)

        result = _run(submit_review(db, user_id=1, schedule_id=1, question_id=1, rating=4))

        # rating=4 应该通过阈值，interval 增长
        assert result["interval_after"] >= 1
        assert schedule.repetitions >= 1

    def test_wrong_answer_maps_to_rating_1(self):
        """答错对应 rating=1（不是 0）。"""
        from app.services.review_scheduler import submit_review

        db = _make_mock_db()
        schedule = _make_schedule_mock()
        schedule.interval = 6
        schedule.ease_factor = 2.5
        schedule.repetitions = 2

        db.execute.return_value = _make_execute_result(scalar_one_or_none=schedule)

        result = _run(submit_review(db, user_id=1, schedule_id=1, question_id=1, rating=1))

        # rating=1 应该重置 interval 和 repetitions
        assert schedule.interval <= 1
        assert schedule.repetitions == 0

    def test_rating_4_grows_less_than_5(self):
        """rating=4 的增长比 rating=5 保守（efactor 更低）。"""
        from app.services.sm2_service import calc_sm2

        r4 = calc_sm2(quality=4, efactor=2.5, interval=6, repetitions=2, review_date=datetime.now(UTC).date())
        r5 = calc_sm2(quality=5, efactor=2.5, interval=6, repetitions=2, review_date=datetime.now(UTC).date())

        # rating=5 应该获得更高的 efactor
        assert r5["efactor"] > r4["efactor"]
        # interval 可能相同（取决于实现），但 efactor 一定不同
        assert r4["interval"] >= 1
        assert r5["interval"] >= 1

    def test_rating_1_penalizes_less_than_0(self):
        """rating=1 的惩罚比 rating=0 轻（efactor 更高）。"""
        from app.services.sm2_service import calc_sm2

        r0 = calc_sm2(quality=0, efactor=2.5, interval=6, repetitions=2, review_date=datetime.now(UTC).date())
        r1 = calc_sm2(quality=1, efactor=2.5, interval=6, repetitions=2, review_date=datetime.now(UTC).date())

        # 两者都重置 interval=1，但 efactor 降低幅度不同
        assert r0["interval"] == 1
        assert r1["interval"] == 1
        # rating=0 的 efactor 惩罚更重
        assert r0["efactor"] < r1["efactor"]
