"""AI 学习引擎服务单元测试。AI 调用全部 mock，不真调 DeepSeek API。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
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


def _make_token_limit_result(used_today=0, used_monthly=0):
    """Mock result for the combined daily/monthly token usage query."""
    m = MagicMock()
    m.one.return_value = (used_today, used_monthly)
    return m


def _patch_chat(call_result=None, side_effect=None):
    """Patch _call_ai（内部已封装 chat_with_db_model + RuntimeError 兜底）。

    - call_result：AI 正常返回（dict 含 content/tokens_used/model/duration_ms）
    - side_effect：置为 None 模拟网关抛 RuntimeError 后的降级路径
    返回 (context manager, mock)。
    """
    target = AsyncMock(return_value=side_effect if side_effect is not None else call_result)
    return patch.object(
        __import__("app.services.ai_learning_service", fromlist=["_call_ai"]),
        "_call_ai",
        target,
    ), target


def _report_row(question_id, is_correct):
    """Row double matching the (question_id, is_correct) report projection."""
    return SimpleNamespace(question_id=question_id, is_correct=is_correct)


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
        """AI 调用失败（RuntimeError 被网关层封装）时返回降级内容。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        # First execute: get question
        # Second execute: load_question_kps rows
        # Third execute: combined daily/monthly token usage
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(all=[(1, "导数")]),
            _make_token_limit_result(0, 0),
        ]

        cm, _mock_call = _patch_chat(side_effect=None)
        with cm:
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
            _make_execute_result(all=[(1, "导数")]),
            _make_token_limit_result(0, 0),
        ]

        cm, _mock_call = _patch_chat(side_effect=None)
        with cm:
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
            _make_execute_result(all=[(1, "导数")]),
            _make_token_limit_result(0, 0),
        ]

        cm, mock_call = _patch_chat(call_result=_make_ai_result())
        with cm:
            result = _run(ai_explain(db, user_id=1, question_id=1))

        assert result["question_id"] == 1
        assert result["from_fallback"] is False
        assert result["tokens_used"] == 150
        assert len(result["solution_steps"]) == 1
        mock_call.assert_awaited_once()

    def test_explain_with_user_answer(self):
        """带用户答案的讲解。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(all=[(1, "导数")]),
            _make_token_limit_result(0, 0),
        ]

        cm, _mock_call = _patch_chat(call_result=_make_ai_result())
        with cm:
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
            _make_execute_result(all=[(1, "导数")]),
            _make_token_limit_result(0, 0),
        ]

        cm, _mock_call = _patch_chat(call_result={
            "content": "这是纯文本解释，不是 JSON",
            "tokens_used": 100,
            "model": "deepseek-chat",
            "duration_ms": 300,
        })
        with cm:
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
            _make_token_limit_result(0, 0),
        ]

        cm, _mock_call = _patch_chat(side_effect=None)
        with cm:
            result = _run(ai_analyze_mistake(db, user_id=1, question_id=1, user_answer="A", correct_answer="C"))

        assert result["from_fallback"] is True

    def test_mistake_analysis_success(self):
        from app.services.ai_learning_service import ai_analyze_mistake

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_token_limit_result(0, 0),
        ]

        cm, _mock_call = _patch_chat(call_result={
            "content": '{"error_type": "概念理解错误", "analysis": "你没有掌握导数的定义", "suggestion": "建议复习导数定义"}',
            "tokens_used": 120,
            "model": "deepseek-chat",
            "duration_ms": 400,
        })
        with cm:
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
            _make_execute_result(all=[(1, "导数"), (10, "导数"), (20, "积分")]),
        ]

        with patch("app.services.vector_retrieval_service.search_similar_questions",
                   new_callable=AsyncMock, return_value={"enabled": False, "recommendations": []}), \
             patch("app.services.ai_learning_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]):
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
            _make_execute_result(all=[]),
        ]

        with patch("app.services.vector_retrieval_service.search_similar_questions",
                   new_callable=AsyncMock, return_value={"enabled": False, "recommendations": []}), \
             patch("app.services.ai_learning_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]):
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
            _make_execute_result(all=[(1, "导数"), (10, "导数")]),
        ]

        with patch("app.services.vector_retrieval_service.search_similar_questions",
                   new_callable=AsyncMock, return_value={"enabled": False, "recommendations": []}), \
             patch("app.services.ai_learning_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]):
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

        result = _run(generate_learning_report(db, user_id=1, subject_id=1, days=7))
        assert result["total_answered"] == 0
        assert result["accuracy"] == 0.0
        assert result["from_fallback"] is True

    def test_insufficient_data(self):
        """数据不足（<5题）时不调用 AI。"""
        from app.services.ai_learning_service import generate_learning_report

        db = _make_mock_db()
        # generate_learning_report reads plain (question_id, is_correct) rows.
        records = [_report_row(1, True), _report_row(2, False)]

        # First execute: records
        # Second execute: db.get(Subject) is used instead; empty KP rows
        db.execute.side_effect = [
            _make_execute_result(all=records),
            _make_execute_result(all=[(1, "导数"), (2, "导数")]),
        ]
        db.get = AsyncMock(return_value=None)

        result = _run(generate_learning_report(db, user_id=1, subject_id=1, days=7))
        assert result["total_answered"] == 2
        assert result["from_fallback"] is False  # No AI call needed, but not a degradation
        assert len(result["learning_suggestions"]) > 0

    def test_report_with_ai_success(self):
        """正常 AI 报告生成。"""
        from app.services.ai_learning_service import generate_learning_report

        db = _make_mock_db()
        # generate_learning_report reads plain (question_id, is_correct) rows.
        records = [_report_row(i + 1, i % 2 == 0) for i in range(10)]

        db.execute.side_effect = [
            _make_execute_result(all=records),               # records
            _make_execute_result(all=[(i, "导数") for i in range(1, 11)]),  # question KPs
            _make_token_limit_result(0, 0),                  # combined token usage
        ]
        db.get = AsyncMock(return_value=None)

        cm, _mock_call = _patch_chat(call_result={
            "content": '{"weak_points": [{"knowledge_point": "导数", "accuracy": 0.5, "suggestion": "多练"}], '
                       '"strong_points": [], "learning_suggestions": ["每天练习5道导数题"]}',
            "tokens_used": 300,
            "model": "deepseek-chat",
            "duration_ms": 600,
        })
        with cm:
            result = _run(generate_learning_report(db, user_id=1, subject_id=1, days=7))

        assert result["total_answered"] == 10
        assert result["from_fallback"] is False
        assert len(result["weak_points"]) >= 1
        assert len(result["learning_suggestions"]) > 0

    def test_report_ai_unavailable(self):
        """AI 不可用时返回规则生成的降级报告。"""
        from app.services.ai_learning_service import generate_learning_report

        db = _make_mock_db()
        records = [_report_row(i + 1, i < 3) for i in range(10)]

        db.execute.side_effect = [
            _make_execute_result(all=records),
            _make_execute_result(all=[(i, "导数") for i in range(1, 11)]),
            _make_token_limit_result(0, 0),
        ]
        db.get = AsyncMock(return_value=None)

        cm, _mock_call = _patch_chat(side_effect=None)
        with cm:
            result = _run(generate_learning_report(db, user_id=1, subject_id=1, days=7))

        assert result["total_answered"] == 10
        assert result["from_fallback"] is True
        assert len(result["learning_suggestions"]) > 0


# ============================================================
# Token 控制测试
# ============================================================


class TestTokenControl:
    def test_within_limit_no_usage(self):
        from app.services.ai_learning_service import check_token_limit

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_token_limit_result(0, 0),  # combined daily/monthly usage
        ]

        result = _run(check_token_limit(db, user_id=1, tokens_needed=100))
        assert result is True

    def test_daily_limit_exceeded(self):
        from app.services.ai_learning_service import check_token_limit

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_token_limit_result(50000, 50000),  # daily & monthly at limit
        ]

        result = _run(check_token_limit(db, user_id=1, tokens_needed=100))
        assert result is False

    def test_monthly_limit_exceeded(self):
        from app.services.ai_learning_service import check_token_limit

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_token_limit_result(100, 500000),  # daily ok, monthly at limit
        ]

        result = _run(check_token_limit(db, user_id=1, tokens_needed=100))
        assert result is False

    def test_limit_disabled_when_zero(self):
        from app.services.ai_learning_service import check_token_limit

        db = _make_mock_db()

        with patch("app.services.ai_learning_service.settings") as mock_settings:
            mock_settings.AI_DAILY_TOKEN_LIMIT = 0
            mock_settings.AI_MONTHLY_TOKEN_LIMIT = 0
            result = _run(check_token_limit(db, user_id=1, tokens_needed=1000000))
            assert result is True

    def test_explain_rejected_when_limit_exceeded(self):
        """Token 超限时讲解返回提示。"""
        from app.services.ai_learning_service import ai_explain

        db = _make_mock_db()
        q = _make_question(1)
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(all=[(1, "导数")]),
            _make_token_limit_result(50000, 50000),  # daily & monthly exceeded
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
