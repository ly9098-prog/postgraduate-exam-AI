"""V5 study_report_service 单元测试。

覆盖 10 个场景：
1. 无数据 overview 返回 0
2. 有数据 overview 正确计算
3. 趋势补零（无刷题日期）
4. due/overdue 计数
5. Leitner 分布
6. 知识点掌握度分类
7. 错题状态划分
8. repeated_wrong 标记
9. subject_id 过滤传递
10. 空 review-plan / wrong-questions 返回空列表
"""
import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.study_report_service import (
    _calc_priority,
    _classify_mastery,
    _extract_title,
    _mastery_suggestion,
    _safe_accuracy,
    get_knowledge_mastery,
    get_leitner_distribution,
    get_overview,
    get_review_plan,
    get_study_trend,
    get_wrong_questions_summary,
)


def _run(coro):
    return asyncio.run(coro)


# ── Mock helpers ─────────────────────────────────────────────────────


class MockRow:
    """同时支持索引访问和属性访问，模拟 SQLAlchemy Row。"""

    def __init__(self, **kwargs):
        self._d = kwargs

    def __getitem__(self, idx):
        return list(self._d.values())[idx]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name)


def _mock_result(*, one_val=None, scalar_val=None, all_vals=None):
    """构造一个模拟 execute 结果。"""
    m = MagicMock()
    if one_val is not None:
        m.one.return_value = one_val
    if scalar_val is not None:
        m.scalar_one.return_value = scalar_val
    if all_vals is not None:
        m.all.return_value = all_vals
    return m


def _make_db(side_effects):
    """db.execute 每次调用按顺序返回不同结果。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=side_effects)
    db.connection = AsyncMock(return_value=SimpleNamespace(
        sync_connection=SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    ))
    return db


# ── 纯函数测试 ──────────────────────────────────────────────────────


class TestPureHelpers:
    def test_safe_accuracy_normal(self):
        assert _safe_accuracy(75, 100) == 75.0

    def test_safe_accuracy_zero(self):
        assert _safe_accuracy(0, 0) == 0.0

    def test_extract_title_from_json_list(self):
        content = json.dumps([{"type": "text", "text": "什么是量子力学？"}])
        assert _extract_title(content) == "什么是量子力学？"

    def test_extract_title_from_plain_string(self):
        assert _extract_title("简单文本") == "简单文本"

    def test_extract_title_truncates(self):
        assert len(_extract_title("x" * 200)) == 100

    def test_extract_title_empty(self):
        assert _extract_title(None) == ""
        assert _extract_title("") == ""

    def test_classify_mastery(self):
        assert _classify_mastery(0.1, 30) == "unknown"  # low confidence
        assert _classify_mastery(0.5, 20) == "weak"
        assert _classify_mastery(0.5, 50) == "normal"
        assert _classify_mastery(0.5, 75) == "good"
        assert _classify_mastery(0.6, 90) == "mastered"

    def test_mastery_suggestion(self):
        assert "优先" in _mastery_suggestion("weak")
        assert "数据较少" in _mastery_suggestion("unknown")
        assert _mastery_suggestion("invalid") == ""

    def test_calc_priority(self):
        assert _calc_priority(5, 0, 3) == "high"  # overdue >= 3
        assert _calc_priority(0, 4, 3) == "high"  # wrong >= 3
        assert _calc_priority(0, 0, 0) == "high"  # box <= 1
        assert _calc_priority(2, 2, 3) == "medium"  # overdue >= 1
        assert _calc_priority(0, 0, 3) == "normal"


# ── Overview 测试 ───────────────────────────────────────────────────


class TestGetOverview:
    def test_empty_data_returns_all_zeros(self):
        """场景 1：用户没有任何记录。"""
        pr_row = MockRow(
            today_count=0, today_correct=0,
            recent_count=0, recent_correct=0,
            total_count=0, total_correct=0,
        )
        db = _make_db([
            _mock_result(one_val=pr_row),   # practice stats
            _mock_result(scalar_val=0),      # due
            _mock_result(scalar_val=0),      # overdue
            _mock_result(scalar_val=0),      # wrong total（前移）
            _mock_result(scalar_val=0),      # repeated wrong（前移）
            _mock_result(scalar_val=0),      # weak
            _mock_result(scalar_val=0),      # unstable
            _mock_result(scalar_val=0),      # mastered
        ])

        result = _run(get_overview(db, user_id=1))
        assert result["today_answer_count"] == 0
        assert result["today_accuracy"] == 0.0
        assert result["total_answer_count"] == 0
        assert result["due_review_count"] == 0
        assert result["wrong_question_count"] == 0

    def test_with_data(self):
        """场景 2：有刷题和复习数据。"""
        pr_row = MockRow(
            today_count=12, today_correct=9,
            recent_count=80, recent_correct=61,
            total_count=360, total_correct=274,
        )
        db = _make_db([
            _mock_result(one_val=pr_row),
            _mock_result(scalar_val=18),  # due
            _mock_result(scalar_val=5),   # overdue
            _mock_result(scalar_val=23),  # wrong total（前移）
            _mock_result(scalar_val=8),   # repeated wrong（前移）
            _mock_result(scalar_val=4),   # weak
            _mock_result(scalar_val=6),   # unstable
            _mock_result(scalar_val=12),  # mastered
        ])

        result = _run(get_overview(db, user_id=1))
        assert result["today_answer_count"] == 12
        assert result["today_correct_count"] == 9
        assert result["today_accuracy"] == 75.0
        assert result["recent_answer_count"] == 80
        assert result["recent_accuracy"] == 76.25
        assert result["total_answer_count"] == 360
        assert result["total_accuracy"] == 76.11
        assert result["due_review_count"] == 18
        assert result["overdue_review_count"] == 5
        assert result["weak_knowledge_count"] == 4
        assert result["unstable_knowledge_count"] == 6
        assert result["mastered_knowledge_count"] == 12
        assert result["wrong_question_count"] == 23
        assert result["repeated_wrong_question_count"] == 8


# ── Review Plan 测试 ────────────────────────────────────────────────


class TestGetReviewPlan:
    def test_empty_returns_empty_list(self):
        """场景 10：无待复习题。"""
        db = _make_db([
            _mock_result(scalar_val=0),  # due count
            _mock_result(scalar_val=0),  # overdue count
            _mock_result(all_vals=[]),   # items
        ])
        result = _run(get_review_plan(db, user_id=1))
        assert result["due_count"] == 0
        assert result["items"] == []

    def test_with_due_items(self):
        """场景 4：有逾期题目，验证 priority 和 overdue_days。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        overdue_date = now - timedelta(days=3)

        db = _make_db([
            _mock_result(scalar_val=2),  # due count
            _mock_result(scalar_val=1),  # overdue count
            _mock_result(all_vals=[
                MockRow(
                    question_id=101, box_level=0, wrong_count=3,
                    correct_count=1, next_review_at=overdue_date,
                ),
            ]),
            _mock_result(all_vals=[
                MockRow(question_id=101, knowledge_point_id=12, name="基础概念"),
            ]),
        ])

        result = _run(get_review_plan(db, user_id=1))
        assert result["due_count"] == 2
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["question_id"] == 101
        assert item["knowledge_point_id"] == 12
        assert item["knowledge_point_name"] == "基础概念"
        assert item["box_level"] == 0
        assert item["wrong_count"] == 3
        assert item["overdue_days"] >= 3
        assert item["priority"] == "high"


# ── Leitner Distribution 测试 ───────────────────────────────────────


class TestGetLeitnerDistribution:
    def test_empty(self):
        db = _make_db([_mock_result(all_vals=[])])
        result = _run(get_leitner_distribution(db, user_id=1))
        assert result["total_tracked_questions"] == 0
        assert len(result["boxes"]) == 6
        assert all(b["count"] == 0 for b in result["boxes"])

    def test_with_data(self):
        """场景 5：各盒子有题目。"""
        db = _make_db([
            _mock_result(all_vals=[
                MockRow(box_level=0, cnt=6),
                MockRow(box_level=2, cnt=18),
                MockRow(box_level=5, cnt=40),
            ]),
        ])
        result = _run(get_leitner_distribution(db, user_id=1))
        assert result["total_tracked_questions"] == 64
        box_map = {b["box_level"]: b for b in result["boxes"]}
        assert box_map[0]["count"] == 6
        assert box_map[0]["label"] == "很不熟"
        assert box_map[1]["count"] == 0  # 缺失的盒子补 0
        assert box_map[2]["count"] == 18
        assert box_map[5]["count"] == 40


# ── Knowledge Mastery 测试 ──────────────────────────────────────────


class TestGetKnowledgeMastery:
    def test_empty(self):
        db = _make_db([_mock_result(all_vals=[])])
        result = _run(get_knowledge_mastery(db, user_id=1))
        assert result["summary"]["weak_count"] == 0
        assert result["items"] == []

    def test_classification(self):
        """场景 6：知识点按 mastery_score + confidence 正确分类。"""
        db = _make_db([
            _mock_result(all_vals=[
                MockRow(
                    knowledge_point_id=1, kp_name="薄弱KP",
                    mastery_score=20.0, confidence=0.8,
                    attempt_count=10, correct_count=2, wrong_count=8,
                    recent_wrong_count=3, last_practiced_at=datetime(2026, 7, 1),
                ),
                MockRow(
                    knowledge_point_id=2, kp_name="正常KP",
                    mastery_score=55.0, confidence=0.6,
                    attempt_count=8, correct_count=4, wrong_count=4,
                    recent_wrong_count=1, last_practiced_at=datetime(2026, 6, 28),
                ),
                MockRow(
                    knowledge_point_id=3, kp_name="掌握KP",
                    mastery_score=92.0, confidence=0.9,
                    attempt_count=20, correct_count=18, wrong_count=2,
                    recent_wrong_count=0, last_practiced_at=datetime(2026, 7, 1),
                ),
                MockRow(
                    knowledge_point_id=4, kp_name="数据不足KP",
                    mastery_score=50.0, confidence=0.1,
                    attempt_count=1, correct_count=0, wrong_count=1,
                    recent_wrong_count=1, last_practiced_at=datetime(2026, 6, 25),
                ),
            ]),
        ])

        result = _run(get_knowledge_mastery(db, user_id=1))
        assert result["summary"]["weak_count"] == 1
        assert result["summary"]["normal_count"] == 1
        assert result["summary"]["mastered_count"] == 1
        assert result["summary"]["unknown_count"] == 1

        item_map = {i["knowledge_point_id"]: i for i in result["items"]}
        assert item_map[1]["status"] == "weak"
        assert "优先" in item_map[1]["suggestion"]
        assert item_map[2]["status"] == "normal"
        assert item_map[3]["status"] == "mastered"
        assert item_map[4]["status"] == "unknown"
        assert "数据较少" in item_map[4]["suggestion"]


# ── Wrong Questions 测试 ────────────────────────────────────────────


class TestGetWrongQuestions:
    def test_empty(self):
        db = _make_db([
            _mock_result(scalar_val=0),  # wrong total
            _mock_result(scalar_val=0),  # repeated
            _mock_result(all_vals=[]),   # detail
        ])
        result = _run(get_wrong_questions_summary(db, user_id=1))
        assert result["wrong_question_count"] == 0
        assert result["items"] == []

    def test_status_classification(self):
        """场景 7 + 8：错题状态划分和 repeated_wrong 标记。"""
        content_json = json.dumps([{"type": "text", "text": "测试题目内容"}])
        db = _make_db([
            _mock_result(scalar_val=3),   # wrong total
            _mock_result(scalar_val=1),   # repeated (wrong_count >= 3)
            _mock_result(all_vals=[
                MockRow(
                    question_id=88, wrong_count=4, correct_count=1,
                    answer_count=5, last_answered_at=datetime(2026, 7, 1),
                    next_review_at=datetime(2026, 7, 2), box_level=0,
                    q_content=content_json,
                ),
                MockRow(
                    question_id=89, wrong_count=1, correct_count=0,
                    answer_count=1, last_answered_at=datetime(2026, 6, 30),
                    next_review_at=datetime(2026, 7, 3), box_level=0,
                    q_content=content_json,
                ),
                MockRow(
                    question_id=90, wrong_count=2, correct_count=3,
                    answer_count=5, last_answered_at=datetime(2026, 6, 29),
                    next_review_at=datetime(2026, 7, 5), box_level=2,
                    q_content=content_json,
                ),
            ]),
            # 批量加载知识点（第 4 次 execute 调用）
            _mock_result(all_vals=[
                MockRow(question_id=88, knowledge_point_id=12, name="基础概念"),
                MockRow(question_id=90, knowledge_point_id=15, name="进阶概念"),
            ]),
        ])

        result = _run(get_wrong_questions_summary(db, user_id=1))
        assert result["wrong_question_count"] == 3
        assert result["repeated_wrong_question_count"] == 1

        item_map = {i["question_id"]: i for i in result["items"]}
        assert item_map[88]["status"] == "repeated_wrong"  # wrong >= 3
        assert item_map[88]["title"] == "测试题目内容"
        assert item_map[88]["knowledge_point_id"] == 12
        assert item_map[88]["knowledge_point_name"] == "基础概念"
        assert item_map[89]["status"] == "not_mastered"    # wrong >= 1, correct == 0
        assert item_map[89]["knowledge_point_id"] is None   # 无 KP 映射
        assert item_map[90]["status"] == "needs_review"    # wrong >= 1, correct > 0
        assert item_map[90]["knowledge_point_id"] == 15


# ── Study Trend 测试 ────────────────────────────────────────────────


class TestGetStudyTrend:
    @pytest.fixture(autouse=True)
    def fixed_china_date(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.study_report_service.shanghai_today", lambda: date(2026, 10, 22)
        )

    def test_empty_fills_zeros(self):
        """场景 3：无刷题记录时，所有日期补零。"""
        db = _make_db([_mock_result(all_vals=[])])
        result = _run(get_study_trend(db, user_id=1, days=7))
        assert len(result["items"]) == 7
        assert all(i["answer_count"] == 0 for i in result["items"])
        assert all(i["accuracy"] == 0.0 for i in result["items"])

    def test_with_data_fills_gaps(self):
        """场景 3：有数据但中间有缺失日期，自动补零。"""
        today = date(2026, 10, 22)
        # 只返回今天和 2 天前的数据
        db = _make_db([
            _mock_result(all_vals=[
                MockRow(d=today.isoformat(), total=10, correct=8),
                MockRow(d=(today - timedelta(days=2)).isoformat(), total=5, correct=3),
            ]),
        ])

        result = _run(get_study_trend(db, user_id=1, days=3))
        assert len(result["items"]) == 3
        # 今天
        assert result["items"][2]["answer_count"] == 10
        assert result["items"][2]["accuracy"] == 80.0
        # 昨天（补零）
        assert result["items"][1]["answer_count"] == 0
        # 前天
        assert result["items"][0]["answer_count"] == 5
        assert result["items"][0]["accuracy"] == 60.0

    @pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
    @pytest.mark.parametrize("date_as_string", [False, True])
    def test_subject_scope_and_china_bucketing(self, dialect, date_as_string):
        from sqlalchemy.dialects import postgresql, sqlite

        from app.core.time_utils import shanghai_date_utc_range

        today = date(2026, 10, 22)
        db = _make_db([_mock_result(all_vals=[
            MockRow(d=today.isoformat() if date_as_string else today, total=4, correct=3),
        ])])
        db.connection.return_value.sync_connection.dialect.name = dialect
        result = _run(get_study_trend(db, user_id=37, subject_id=9, days=3))
        assert [item["answer_count"] for item in result["items"]] == [0, 0, 4]
        assert result["items"][-1]["accuracy"] == 75.0
        assert result["items"][0]["date"] == "2026-10-20"
        db.connection.assert_awaited_once()
        compiled = db.execute.await_args.args[0].compile(
            dialect=sqlite.dialect() if dialect == "sqlite" else postgresql.dialect()
        )
        sql = str(compiled)
        assert "practice_records.user_id =" in sql
        assert "practice_records.subject_id =" in sql
        assert {37, 9} <= set(compiled.params.values())
        assert shanghai_date_utc_range(today - timedelta(days=2))[0] in compiled.params.values()
        if dialect == "sqlite":
            assert "+8 hours" in compiled.params.values()
        else:
            assert "INTERVAL '8 hours' AS DATE" in sql


# ── subject_id 过滤路径测试 ─────────────────────────────────────────


class TestOverviewSubjectFilter:
    """subject_id 过滤走 _subject_exists + subject_id 过滤路径（知识点）
    和 JOIN 路径（UserQuestionState / PracticeRecord）。"""

    @patch("app.services.study_report_service._subject_exists")
    def test_overview_with_subject_id(self, mock_resolve):
        """subject_id 存在时，_subject_exists 被调用，所有统计正常返回。"""
        mock_resolve.return_value = True

        pr_row = MockRow(
            today_count=5, today_correct=4,
            recent_count=30, recent_correct=22,
            total_count=100, total_correct=75,
        )
        db = _make_db([
            _mock_result(one_val=pr_row),       # practice stats (JOIN Question)
            _mock_result(scalar_val=10),         # due (JOIN Question)
            _mock_result(scalar_val=3),          # overdue (JOIN Question)
            _mock_result(scalar_val=15),         # wrong total (JOIN Question)
            _mock_result(scalar_val=5),          # repeated wrong (JOIN Question)
            _mock_result(scalar_val=2),          # weak (IN subject_codes)
            _mock_result(scalar_val=4),          # unstable (IN subject_codes)
            _mock_result(scalar_val=8),          # mastered (IN subject_codes)
        ])

        result = _run(get_overview(db, user_id=1, subject_id=1))

        mock_resolve.assert_called_once_with(db, 1)
        assert result["today_answer_count"] == 5
        assert result["due_review_count"] == 10
        assert result["overdue_review_count"] == 3
        assert result["weak_knowledge_count"] == 2
        assert result["unstable_knowledge_count"] == 4
        assert result["mastered_knowledge_count"] == 8
        assert result["wrong_question_count"] == 15
        assert result["repeated_wrong_question_count"] == 5

    @patch("app.services.study_report_service._subject_exists")
    def test_overview_empty_subject_codes_early_return(self, mock_resolve):
        """subject_id 不存在时，知识点返回 0，但错题统计仍正确（已前移）。"""
        mock_resolve.return_value = False

        pr_row = MockRow(
            today_count=0, today_correct=0,
            recent_count=0, recent_correct=0,
            total_count=0, total_correct=0,
        )
        db = _make_db([
            _mock_result(one_val=pr_row),   # practice stats
            _mock_result(scalar_val=0),      # due
            _mock_result(scalar_val=0),      # overdue
            _mock_result(scalar_val=7),      # wrong total（早返回前已计算）
            _mock_result(scalar_val=2),      # repeated wrong（早返回前已计算）
            # 不应再调用知识点相关查询
        ])

        result = _run(get_overview(db, user_id=1, subject_id=999))

        mock_resolve.assert_called_once_with(db, 999)
        # 知识点全部为 0
        assert result["weak_knowledge_count"] == 0
        assert result["unstable_knowledge_count"] == 0
        assert result["mastered_knowledge_count"] == 0
        # 错题统计不受影响
        assert result["wrong_question_count"] == 7
        assert result["repeated_wrong_question_count"] == 2
        # 只调用了 5 次（practice + due + overdue + wrong×2），未进入知识点查询
        assert db.execute.call_count == 5


class TestKnowledgeMasterySubjectFilter:
    """get_knowledge_mastery 通过 _subject_exists + subject_id 过滤。"""

    @patch("app.services.study_report_service._subject_exists")
    def test_knowledge_mastery_with_subject_id(self, mock_resolve):
        mock_resolve.return_value = True

        db = _make_db([
            _mock_result(all_vals=[
                MockRow(
                    knowledge_point_id=1, kp_name="高数",
                    mastery_score=30.0, confidence=0.9,
                    attempt_count=10, correct_count=3, wrong_count=7,
                    recent_wrong_count=2, last_practiced_at=datetime(2026, 7, 1),
                ),
            ]),
        ])

        result = _run(get_knowledge_mastery(db, user_id=1, subject_id=1))

        mock_resolve.assert_called_once_with(db, 1)
        assert result["summary"]["weak_count"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["status"] == "weak"

    @patch("app.services.study_report_service._subject_exists")
    def test_knowledge_mastery_empty_subject_codes(self, mock_resolve):
        mock_resolve.return_value = False
        db = _make_db([])

        result = _run(get_knowledge_mastery(db, user_id=1, subject_id=999))

        mock_resolve.assert_called_once_with(db, 999)
        assert result["summary"]["weak_count"] == 0
        assert result["items"] == []
        # 无 DB 查询（早返回）
        db.execute.assert_not_called()


class TestWrongQuestionsSubjectFilter:
    """get_wrong_questions_summary 通过 JOIN Question.subject_id 过滤，
    不经过 _subject_exists（与 UserKnowledgeState 路径不同）。"""

    def test_wrong_questions_with_subject_id(self):
        """subject_id 存在时，JOIN 路径正常工作。"""
        content_json = json.dumps([{"type": "text", "text": "题目内容"}])
        db = _make_db([
            _mock_result(scalar_val=1),   # count_q (with JOIN)
            _mock_result(scalar_val=0),   # repeated_q (with JOIN)
            _mock_result(all_vals=[
                MockRow(
                    question_id=50, wrong_count=2, correct_count=1,
                    answer_count=3, last_answered_at=datetime(2026, 7, 1),
                    next_review_at=datetime(2026, 7, 3), box_level=1,
                    q_content=content_json,
                ),
            ]),
            _mock_result(all_vals=[
                MockRow(question_id=50, knowledge_point_id=7, name="线性代数"),
            ]),
        ])

        result = _run(get_wrong_questions_summary(db, user_id=1, subject_id=1))

        assert result["wrong_question_count"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["knowledge_point_id"] == 7
        assert result["items"][0]["knowledge_point_name"] == "线性代数"
