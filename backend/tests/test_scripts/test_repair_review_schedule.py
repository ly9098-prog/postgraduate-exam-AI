"""repair_review_schedule_for_wrong_questions 脚本测试。"""
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from scripts.repair_review_schedule_for_wrong_questions import repair_review_schedule

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
from app.models.review_scheduler import ReviewSchedule  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


class TestRepairReviewSchedule:
    def test_no_wrong_questions(self, monkeypatch):
        """无 WrongQuestion 时不创建。"""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        # 返回空列表
        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_wq_result

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        result = _run(repair_review_schedule(apply=False))

        assert result["scanned"] == 0
        assert result["created"] == 0

    def test_all_have_schedule_dry_run(self, monkeypatch):
        """所有 WrongQuestion 都已存在 ReviewSchedule 时，dry-run 不创建。"""
        mock_db = MagicMock()

        # 返回 1 条 WrongQuestion
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.user_id = 1
        mock_wq.question_id = 1
        mock_wq.mastered = False
        mock_wq.last_review_at = None

        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = [mock_wq]

        # 返回已存在的 ReviewSchedule
        mock_schedule = MagicMock()
        mock_schedule_result = MagicMock()
        mock_schedule_result.scalar_one_or_none.return_value = mock_schedule

        # 第一次 execute 返回 WrongQuestion，第二次返回 ReviewSchedule
        mock_db.execute = AsyncMock(side_effect=[mock_wq_result, mock_schedule_result])

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        result = _run(repair_review_schedule(apply=False))

        assert result["scanned"] == 1
        assert result["exists"] == 1
        assert result["need_repair"] == 0
        assert result["created"] == 0

    def test_missing_schedule_dry_run(self, monkeypatch):
        """缺失 ReviewSchedule 时，dry-run 不创建。"""
        mock_db = MagicMock()

        # 返回 1 条 WrongQuestion
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.user_id = 1
        mock_wq.question_id = 1
        mock_wq.mastered = False
        mock_wq.last_review_at = None

        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = [mock_wq]

        # 返回不存在的 ReviewSchedule
        mock_schedule_result = MagicMock()
        mock_schedule_result.scalar_one_or_none.return_value = None

        # 返回 Question
        mock_question = MagicMock()
        mock_question.subject_id = 1
        mock_question_result = MagicMock()
        mock_question_result.scalar_one_or_none.return_value = mock_question

        mock_db.execute = AsyncMock(side_effect=[mock_wq_result, mock_schedule_result, mock_question_result])

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        result = _run(repair_review_schedule(apply=False))

        assert result["scanned"] == 1
        assert result["exists"] == 0
        assert result["need_repair"] == 1
        assert result["created"] == 0  # dry-run 不创建

    def test_missing_schedule_apply(self, monkeypatch):
        """缺失 ReviewSchedule 时，apply 创建。"""
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # 返回 1 条 WrongQuestion
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.user_id = 1
        mock_wq.question_id = 1
        mock_wq.mastered = False
        mock_wq.last_review_at = None

        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = [mock_wq]

        # 返回不存在的 ReviewSchedule
        mock_schedule_result = MagicMock()
        mock_schedule_result.scalar_one_or_none.return_value = None

        # 返回 Question
        mock_question = MagicMock()
        mock_question.subject_id = 1
        mock_question_result = MagicMock()
        mock_question_result.scalar_one_or_none.return_value = mock_question

        mock_db.execute = AsyncMock(side_effect=[mock_wq_result, mock_schedule_result, mock_question_result])

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        result = _run(repair_review_schedule(apply=True))

        assert result["scanned"] == 1
        assert result["exists"] == 0
        assert result["need_repair"] == 1
        assert result["created"] == 1
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_idempotent_apply(self, monkeypatch):
        """重复运行不重复创建（幂等性）。"""
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # 返回 1 条 WrongQuestion
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.user_id = 1
        mock_wq.question_id = 1
        mock_wq.mastered = False
        mock_wq.last_review_at = None

        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = [mock_wq]

        # 第一次返回不存在，第二次返回已存在
        mock_schedule_result_1 = MagicMock()
        mock_schedule_result_1.scalar_one_or_none.return_value = None

        mock_schedule_result_2 = MagicMock()
        mock_schedule_result_2.scalar_one_or_none.return_value = MagicMock()

        # 返回 Question
        mock_question = MagicMock()
        mock_question.subject_id = 1
        mock_question_result = MagicMock()
        mock_question_result.scalar_one_or_none.return_value = mock_question

        mock_db.execute = AsyncMock(side_effect=[
            mock_wq_result,
            mock_schedule_result_1,
            mock_question_result,
        ])

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        # 第一次运行
        result_1 = _run(repair_review_schedule(apply=True))
        assert result_1["created"] == 1

        # 第二次运行（模拟已存在）
        mock_db.execute = AsyncMock(side_effect=[
            mock_wq_result,
            mock_schedule_result_2,
        ])
        result_2 = _run(repair_review_schedule(apply=True))
        assert result_2["exists"] == 1
        assert result_2["created"] == 0

    def test_subject_backfilled(self, monkeypatch):
        """subject 从 Question 正确回填。"""
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # 返回 1 条 WrongQuestion
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.user_id = 1
        mock_wq.question_id = 1
        mock_wq.mastered = False
        mock_wq.last_review_at = None

        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = [mock_wq]

        # 返回不存在的 ReviewSchedule
        mock_schedule_result = MagicMock()
        mock_schedule_result.scalar_one_or_none.return_value = None

        # 返回 Question with subject
        mock_question = MagicMock()
        mock_question.subject_id = 9
        mock_question_result = MagicMock()
        mock_question_result.scalar_one_or_none.return_value = mock_question

        mock_db.execute = AsyncMock(side_effect=[mock_wq_result, mock_schedule_result, mock_question_result])

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        result = _run(repair_review_schedule(apply=True))

        assert result["created"] == 1
        # 验证 add 的 ReviewSchedule 的 subject
        added_schedule = mock_db.add.call_args[0][0]
        assert added_schedule.subject_id == 9

    def test_mastered_inherited(self, monkeypatch):
        """mastered 从 WrongQuestion 正确继承。"""
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # 返回 1 条 mastered=True 的 WrongQuestion
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.user_id = 1
        mock_wq.question_id = 1
        mock_wq.mastered = True
        mock_wq.last_review_at = datetime(2026, 1, 1, tzinfo=UTC)

        mock_wq_result = MagicMock()
        mock_wq_result.scalars.return_value.all.return_value = [mock_wq]

        # 返回不存在的 ReviewSchedule
        mock_schedule_result = MagicMock()
        mock_schedule_result.scalar_one_or_none.return_value = None

        # 返回 Question
        mock_question = MagicMock()
        mock_question.subject_id = 1
        mock_question_result = MagicMock()
        mock_question_result.scalar_one_or_none.return_value = mock_question

        mock_db.execute = AsyncMock(side_effect=[mock_wq_result, mock_schedule_result, mock_question_result])

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("scripts.repair_review_schedule_for_wrong_questions.async_session", lambda: mock_session)

        result = _run(repair_review_schedule(apply=True))

        assert result["created"] == 1
        # 验证 add 的 ReviewSchedule 的 mastered
        added_schedule = mock_db.add.call_args[0][0]
        assert added_schedule.mastered is True
        assert added_schedule.last_reviewed_at == mock_wq.last_review_at
