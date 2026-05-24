"""AI 学习引擎服务单元测试。AI 调用全部 mock，不真调 DeepSeek API。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ai_chat import AiChat
from app.models.question import Question


# ============================================================
# Test Helpers
# ============================================================


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
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        elif method == "all":
            mock_result.all.return_value = value
        elif method == "one":
            mock_result.one.return_value = value
        elif method == "scalar":
            mock_result.scalar.return_value = value
        elif method == "scalar_one_or_none":
            mock_result.scalar_one_or_none.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _make_question(id=1, subject="math2", question_type="single_choice",
                   answer="A", analysis="求导得 2x", knowledge_points=None,
                   is_active=True, difficulty=2, review_status="approved"):
    q = MagicMock(spec=Question)
    q.id = id
    q.subject = subject
    q.question_type = question_type
    q.content = {"text": "f(x)=x^2, f'(x)=?"}
    q.options = {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
    q.answer = answer
    q.analysis = analysis
    q.knowledge_points = knowledge_points or ["导数"]
    q.difficulty = difficulty
    q.is_active = is_active
    q.review_status = review_status
    return q


def _make_ai_result(content='{"explanation": "测试讲解", "solution_steps": ["s1"], "key_knowledge_points": ["导数"], "common_mistakes": ["忘了链式法则"]}'):
    return {
        "content": content,
        "tokens_used": 150,
        "model": "deepseek-chat",
        "duration_ms": 500,
    }


# ============================================================
# JSON 解析测试（纯函数，无需 DB）
# ============================================================


class TestParseJsonResponse:
    def test_direct_json(self):
        from app.services.ai_learning_service import _parse_json_response

        result = _parse_json_response('{"explanation": "hello", "solution_steps": ["s1"]}')
        assert result == {"explanation": "hello", "solution_steps": ["s1"]}

    def test_json_with_markdown_fence(self):
        from app.services.ai_learning_service import _parse_json_response

        content = 'some\n```json\n{"explanation": "hello"}\n```\nmore'
        result = _parse_json_response(content)
        assert result == {"explanation": "hello"}

    def test_json_without_lang_fence(self):
        from app.services.ai_learning_service import _parse_json_response

        content = '```\n{"analysis": "bad"}\n```'
        result = _parse_json_response(content)
        assert result == {"analysis": "bad"}

    def test_nested_braces(self):
        from app.services.ai_learning_service import _parse_json_response

        content = '{"weak_points": [{"knowledge_point": "导数", "accuracy": 0.5}], "learning_suggestions": ["a"]}'
        result = _parse_json_response(content)
        assert result["learning_suggestions"] == ["a"]
        assert len(result["weak_points"]) == 1

    def test_invalid_json(self):
        from app.services.ai_learning_service import _parse_json_response

        assert _parse_json_response("not json at all") is None

    def test_empty(self):
        from app.services.ai_learning_service import _parse_json_response

        assert _parse_json_response("") is None


# ============================================================
# AI 讲解测试
# ============================================================


class TestAIExplain:
    def test_question_not_found(self):
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with pytest.raises(ValueError, match="题目不存在"):
            _run(ai_explain(db, user_id=1, question_id=99999))

    def test_ai_unavailable_graceful(self):
        """AI API 不可用时返回降级内容。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        # First execute: get question → ok
        # Second execute: token check (daily sum) → 0
        # Third execute: token check (monthly sum) → 0
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = False
            result = _run(ai_explain(db, user_id=1, question_id=1))

        assert result["question_id"] == 1
        assert result["from_fallback"] is True
        assert len(result["explanation"]) > 0

    def test_api_exception_degradation(self):
        """AI API 抛异常时返回降级内容。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = True
            mock_ds.chat = AsyncMock(side_effect=RuntimeError("API error"))
            result = _run(ai_explain(db, user_id=1, question_id=1))

        assert result["from_fallback"] is True
        assert len(result["explanation"]) > 0

    def test_successful_explain(self):
        """正常 AI 讲解调用。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = True
            mock_ds.chat = AsyncMock(return_value=_make_ai_result())
            result = _run(ai_explain(db, user_id=1, question_id=1))

        assert result["question_id"] == 1
        assert result["from_fallback"] is False
        assert result["tokens_used"] == 150
        assert len(result["solution_steps"]) == 1

    def test_explain_with_user_answer(self):
        """带用户答案的讲解。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = True
            mock_ds.chat = AsyncMock(return_value=_make_ai_result())
            result = _run(ai_explain(
                db, user_id=1, question_id=1,
                user_answer="B", is_correct=False, focus="mistake",
            ))

        assert result["from_fallback"] is False

    def test_explain_malformed_ai_response(self):
        """AI 返回非 JSON 时也能处理。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = True
            mock_ds.chat = AsyncMock(return_value={
                "content": "这是纯文本解释，不是 JSON",
                "tokens_used": 100,
                "model": "deepseek-chat",
                "duration_ms": 300,
            })
            result = _run(ai_explain(db, user_id=1, question_id=1))

        assert result["from_fallback"] is False
        assert "纯文本" in result["explanation"]


# ============================================================
# 错因分析测试
# ============================================================


class TestMistakeAnalysis:
    def test_question_not_found(self):
        from app.services.ai_learning_service import ai_analyze_mistake

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with pytest.raises(ValueError, match="题目不存在"):
            _run(ai_analyze_mistake(db, user_id=1, question_id=99999, user_answer="A", correct_answer="B"))

    def test_ai_unavailable(self):
        """AI 不可用时返回降级。"""
        from app.services.ai_learning_service import ai_analyze_mistake

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = False
            result = _run(ai_analyze_mistake(db, user_id=1, question_id=1, user_answer="A", correct_answer="C"))

        assert result["from_fallback"] is True

    def test_mistake_analysis_success(self):
        from app.services.ai_learning_service import ai_analyze_mistake

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = True
            mock_ds.chat = AsyncMock(return_value={
                "content": '{"error_type": "概念理解错误", "analysis": "你没有掌握导数的定义", "suggestion": "建议复习导数定义"}',
                "tokens_used": 120,
                "model": "deepseek-chat",
                "duration_ms": 400,
            })
            result = _run(ai_analyze_mistake(db, user_id=1, question_id=1, user_answer="A", correct_answer="C"))

        assert result["from_fallback"] is False
        assert result["error_type"] == "概念理解错误"
        assert result["error_type_label"] == "概念理解错误"
        assert result["tokens_used"] == 120


# ============================================================
# 相似题推荐测试
# ============================================================


class TestRecommend:
    def test_question_not_found(self):
        from app.services.ai_learning_service import recommend_similar_questions

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with pytest.raises(ValueError, match="题目不存在"):
            _run(recommend_similar_questions(db, user_id=1, question_id=99999))

    def test_recommend_exclude_self(self):
        """推荐结果不包含自身题目。"""
        from app.services.ai_learning_service import recommend_similar_questions

        db = _make_mock_db()
        q_self = _make_question(1, knowledge_points=["导数"])
        q_similar = _make_question(10, knowledge_points=["导数"])
        q_diff = _make_question(20, knowledge_points=["积分"])

        # 第一次 execute: get the source question
        # 第二次 execute: get answered question_ids (returns empty)
        # 第三次 execute: get candidates (returns all 3 including self, but self filtered by SQL)
        # Actually the filter logic: answered_ids includes question_id=1 (self) + user answered (none in mock)
        # So candidates should only include questions != 1
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q_self),
            _make_execute_result(all=[]),  # no answered questions
            _make_execute_result(scalars=[q_similar, q_diff]),
        ]

        result = _run(recommend_similar_questions(db, user_id=1, question_id=1, count=5))
        assert result["source_question_id"] == 1
        assert result["strategy"] == "rule_based"
        # q_diff has no overlapping kp, so only q_similar should match
        qids = [r["question_id"] for r in result["recommendations"]]
        assert 1 not in qids  # self excluded
        assert 10 in qids     # same KP

    def test_empty_result(self):
        """无相似题时返回空列表。"""
        from app.services.ai_learning_service import recommend_similar_questions

        db = _make_mock_db()
        q = _make_question(1, knowledge_points=["导数"])
        # No other questions
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(all=[]),
            _make_execute_result(scalars=[]),
        ]

        result = _run(recommend_similar_questions(db, user_id=1, question_id=1))
        assert result["recommendations"] == []

    def test_recommend_exclude_answered(self):
        """已做题被排除。"""
        from app.services.ai_learning_service import recommend_similar_questions

        db = _make_mock_db()
        q_self = _make_question(1, knowledge_points=["导数"])
        q_answered = _make_question(10, knowledge_points=["导数"])

        # User has already answered question 10
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q_self),
            _make_execute_result(all=[(10,)]),  # answered qid=10
            _make_execute_result(scalars=[q_answered]),  # candidate
        ]

        result = _run(recommend_similar_questions(db, user_id=1, question_id=1))
        qids = [r["question_id"] for r in result["recommendations"]]
        assert 10 not in qids


# ============================================================
# 学习报告测试
# ============================================================


class TestLearningReport:
    def test_empty_data(self):
        from app.services.ai_learning_service import generate_learning_report

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalars=[])

        result = _run(generate_learning_report(db, user_id=1, subject="math2", days=7))
        assert result["total_answered"] == 0
        assert result["accuracy"] == 0.0
        assert result["from_fallback"] is True

    def test_insufficient_data(self):
        """数据不足（<5题）时不调用 AI。"""
        from app.services.ai_learning_service import generate_learning_report
        from app.models.practice_record import PracticeRecord

        db = _make_mock_db()
        r1 = MagicMock(spec=PracticeRecord)
        r1.question_id = 1
        r1.is_correct = True
        r1.subject = "math2"

        r2 = MagicMock(spec=PracticeRecord)
        r2.question_id = 2
        r2.is_correct = False
        r2.subject = "math2"

        # First execute: records
        # Second execute: questions with knowledge_points
        db.execute.side_effect = [
            _make_execute_result(scalars=[r1, r2]),
            _make_execute_result(all=[(1, ["导数"]), (2, ["导数"])]),
        ]

        result = _run(generate_learning_report(db, user_id=1, subject="math2", days=7))
        assert result["total_answered"] == 2
        assert result["from_fallback"] is False  # No AI call needed, but not a degradation
        assert len(result["learning_suggestions"]) > 0

    def test_report_with_ai_success(self):
        """正常 AI 报告生成。"""
        from app.services.ai_learning_service import generate_learning_report
        from app.models.practice_record import PracticeRecord

        db = _make_mock_db()
        records = []
        for i in range(10):
            r = MagicMock(spec=PracticeRecord)
            r.question_id = i + 1
            r.is_correct = i % 2 == 0  # half correct
            r.subject = "math2"
            records.append(r)

        db.execute.side_effect = [
            _make_execute_result(scalars=records),      # records
            _make_execute_result(all=[(i, ["导数"]) for i in range(1, 11)]),  # question KPs
            _make_execute_result(scalar=0),              # daily token check
            _make_execute_result(scalar=0),              # monthly token check
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = True
            mock_ds.chat = AsyncMock(return_value={
                "content": '{"weak_points": [{"knowledge_point": "导数", "accuracy": 0.5, "suggestion": "多练"}], '
                           '"strong_points": [], "learning_suggestions": ["每天练习5道导数题"]}',
                "tokens_used": 300,
                "model": "deepseek-chat",
                "duration_ms": 600,
            })
            result = _run(generate_learning_report(db, user_id=1, subject="math2", days=7))

        assert result["total_answered"] == 10
        assert result["from_fallback"] is False
        assert len(result["weak_points"]) == 1
        assert len(result["learning_suggestions"]) > 0

    def test_report_ai_unavailable(self):
        """AI 不可用时返回规则生成的降级报告。"""
        from app.services.ai_learning_service import generate_learning_report
        from app.models.practice_record import PracticeRecord

        db = _make_mock_db()
        records = []
        for i in range(10):
            r = MagicMock(spec=PracticeRecord)
            r.question_id = i + 1
            r.is_correct = i < 3  # only 3 correct → 30%
            r.subject = "math2"
            records.append(r)

        db.execute.side_effect = [
            _make_execute_result(scalars=records),
            _make_execute_result(all=[(i, ["导数"]) for i in range(1, 11)]),
            _make_execute_result(scalar=0),
            _make_execute_result(scalar=0),
        ]

        with patch("app.services.ai_learning_service.deepseek") as mock_ds:
            mock_ds.is_available.return_value = False
            result = _run(generate_learning_report(db, user_id=1, subject="math2", days=7))

        assert result["total_answered"] == 10
        assert result["from_fallback"] is True
        assert len(result["learning_suggestions"]) > 0


# ============================================================
# Token 控制测试
# ============================================================


class TestTokenControl:
    def test_within_limit_no_usage(self):
        from app.services.ai_learning_service import _check_token_limit

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalar=0),  # daily
            _make_execute_result(scalar=0),  # monthly
        ]

        result = _run(_check_token_limit(db, user_id=1, tokens_needed=100))
        assert result is True

    def test_daily_limit_exceeded(self):
        from app.services.ai_learning_service import _check_token_limit

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalar=50000),  # daily: at limit
            _make_execute_result(scalar=50000),  # monthly: also at limit
        ]

        result = _run(_check_token_limit(db, user_id=1, tokens_needed=100))
        assert result is False

    def test_monthly_limit_exceeded(self):
        from app.services.ai_learning_service import _check_token_limit

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalar=100),    # daily: ok
            _make_execute_result(scalar=500000),  # monthly: at limit
        ]

        result = _run(_check_token_limit(db, user_id=1, tokens_needed=100))
        assert result is False

    def test_limit_disabled_when_zero(self):
        from app.services.ai_learning_service import _check_token_limit

        db = _make_mock_db()

        with patch("app.services.ai_learning_service.settings") as mock_settings:
            mock_settings.AI_DAILY_TOKEN_LIMIT = 0
            mock_settings.AI_MONTHLY_TOKEN_LIMIT = 0
            result = _run(_check_token_limit(db, user_id=1, tokens_needed=1000000))
            assert result is True

    def test_explain_rejected_when_limit_exceeded(self):
        """Token 超限时讲解返回提示。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar=50000),  # daily: exceeded
            _make_execute_result(scalar=50000),  # monthly: exceeded
        ]

        result = _run(ai_explain(db, user_id=1, question_id=1))
        assert result["from_fallback"] is True
        assert "额度" in result["explanation"]


# ============================================================
# 降级内容测试
# ============================================================


class TestFallbackContent:
    def test_fallback_explain_has_explanation(self):
        from app.ai.fallback import get_fallback_explain

        fb = get_fallback_explain()
        assert "explanation" in fb
        assert len(fb["explanation"]) > 0

    def test_fallback_report_has_suggestions(self):
        from app.ai.fallback import get_fallback_report

        fb = get_fallback_report()
        assert "learning_suggestions" in fb
        assert len(fb["learning_suggestions"]) > 0

    def test_fallback_mistake_analysis(self):
        from app.ai.fallback import get_fallback_mistake_analysis

        fb = get_fallback_mistake_analysis()
        assert "analysis" in fb
        assert "suggestion" in fb
        assert len(fb["analysis"]) > 0
