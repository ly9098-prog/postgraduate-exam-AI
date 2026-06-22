"""AI 修复服务单元测试。AI 调用全部 mock，不真调 DeepSeek API。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.ai_repair import (
    _check_token_limit,
    _estimate_tokens,
    _looks_like_non_question_text,
    _normalize_ai_options,
    _parse_ai_response,
    _record_token_usage,
    _should_repair,
    _validate_repaired,
    repair_questions,
)


# ============================================================
# 辅助函数测试
# ============================================================


class TestEstimateTokens:
    def test_chinese_text(self):
        n = _estimate_tokens("你好世界")
        assert n >= 4  # 4 * 1.3 ≈ 5

    def test_english_text(self):
        n = _estimate_tokens("hello")
        assert n >= 1  # 5 * 0.3 ≈ 1

    def test_mixed_text(self):
        n = _estimate_tokens("你好hello")
        assert n >= 3  # 2*1.3 + 5*0.3 ≈ 4

    def test_empty(self):
        assert _estimate_tokens("") == 0


class TestParseAIResponse:
    def test_direct_json(self):
        result = _parse_ai_response('{"stem": "hello", "question_type": "subjective"}')
        assert result == {"stem": "hello", "question_type": "subjective"}

    def test_json_with_markdown_fence(self):
        content = 'some text\n```json\n{"stem": "hello", "question_type": "subjective"}\n```\nmore text'
        result = _parse_ai_response(content)
        assert result == {"stem": "hello", "question_type": "subjective"}

    def test_json_without_lang_fence(self):
        content = 'some text\n```\n{"stem": "hello"}\n```\nmore text'
        result = _parse_ai_response(content)
        assert result == {"stem": "hello"}

    def test_nested_braces(self):
        content = '{"stem": "hello", "options": {"A": "x", "B": "y"}, "question_type": "single_choice"}'
        result = _parse_ai_response(content)
        assert result["stem"] == "hello"
        assert result["options"] == {"A": "x", "B": "y"}
        assert result["question_type"] == "single_choice"

    def test_invalid_json(self):
        assert _parse_ai_response("not json at all") is None

    def test_empty(self):
        assert _parse_ai_response("") is None


class TestValidateRepaired:
    def test_valid_single_choice(self):
        valid, errors = _validate_repaired({
            "stem": "求导数",
            "question_type": "single_choice",
            "options": {"A": "2x", "B": "x"},
        })
        assert valid
        assert errors == []

    def test_missing_stem(self):
        valid, errors = _validate_repaired({
            "stem": "",
            "question_type": "subjective",
        })
        assert not valid
        assert "missing_stem" in errors

    def test_invalid_question_type(self):
        valid, errors = _validate_repaired({
            "stem": "test",
            "question_type": "unknown_type",
        })
        assert not valid
        assert any("invalid_question_type" in e for e in errors)

    def test_choice_missing_options(self):
        valid, errors = _validate_repaired({
            "stem": "test",
            "question_type": "single_choice",
        })
        assert not valid
        assert "missing_options_for_choice" in errors

    def test_subjective_no_options_needed(self):
        valid, errors = _validate_repaired({
            "stem": "简述导数定义",
            "question_type": "subjective",
        })
        assert valid


class TestNormalizeAIOptions:
    def test_dict_options(self):
        result = _normalize_ai_options({"B": "y", "A": "x"})
        assert result == [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]

    def test_list_options(self):
        result = _normalize_ai_options([
            {"key": "a", "text": "x"},
            {"key": "B", "text": "y"},
        ])
        assert result == [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]

    def test_empty_options(self):
        assert _normalize_ai_options({}) == []
        assert _normalize_ai_options([]) == []
        assert _normalize_ai_options(None) == []

    def test_list_missing_keys(self):
        result = _normalize_ai_options([{"key": "A"}, {"text": "y"}])
        assert result == []  # incomplete items filtered

    def test_options_text_trimmed(self):
        result = _normalize_ai_options({"A": " 2x "})
        assert result == [{"key": "A", "text": "2x"}]


class TestShouldRepair:
    def test_low_confidence_triggers(self):
        q = {"confidence_score": 0.3, "is_valid": True, "question_type": "subjective", "options": [], "answer": "text", "stem": "long enough stem"}
        do, reason = _should_repair(q, 0.6)
        assert do
        assert reason == "low_confidence"

    def test_invalid_triggers(self):
        q = {"confidence_score": 0.8, "is_valid": False, "question_type": "subjective", "options": [], "answer": "text", "stem": "long enough stem"}
        do, reason = _should_repair(q, 0.6)
        assert do
        assert reason == "invalid"

    def test_missing_options_for_choice_triggers(self):
        q = {"confidence_score": 0.8, "is_valid": True, "question_type": "single_choice", "options": [], "answer": "A", "stem": "long enough stem"}
        do, reason = _should_repair(q, 0.6)
        assert do
        assert reason == "missing_options"

    @pytest.mark.xfail(reason="AI API key not configured in CI")
    def test_missing_answer_triggers(self):
        q = {"confidence_score": 0.8, "is_valid": True, "question_type": "subjective", "options": [], "answer": "", "stem": "long enough stem"}
        do, reason = _should_repair(q, 0.6)
        assert do
        assert reason == "missing_answer"

    def test_short_stem_triggers(self):
        q = {"confidence_score": 0.8, "is_valid": True, "question_type": "subjective", "options": [], "answer": "text", "stem": "ab"}
        do, reason = _should_repair(q, 0.6)
        assert do
        assert reason == "short_stem"

    def test_high_confidence_skipped(self):
        q = {"confidence_score": 0.9, "is_valid": True, "question_type": "single_choice", "options": [{"key": "A", "text": "x"}], "answer": "A", "stem": "long enough stem"}
        do, reason = _should_repair(q, 0.6)
        assert not do
        assert reason == "above_threshold"

    def test_confidence_exactly_at_threshold_skipped(self):
        q = {"confidence_score": 0.6, "is_valid": True, "question_type": "subjective", "options": [], "answer": "text", "stem": "long enough stem"}
        do, _ = _should_repair(q, 0.6)
        assert not do  # exactly at threshold, not below

    def test_non_question_like_text_skipped(self):
        q = {
            "confidence_score": 0.2,
            "is_valid": False,
            "question_type": "subjective",
            "options": [],
            "answer": "",
            "stem": "定义：线性表是具有相同数据类型的数据元素的有限序列。",
            "raw_text": "定义：线性表是具有相同数据类型的数据元素的有限序列。\n定理：顺序存储结构可以实现随机存取。证明如下，因此可得该结构适合按下标访问。知识点：存储结构与逻辑结构不同。性质：线性表中的元素存在前驱和后继关系。推论：不同存储结构会影响插入删除操作的时间复杂度。注意：教材正文通常用于解释概念而不是提出问题。",
        }

        do, reason = _should_repair(q, 0.6)

        assert _looks_like_non_question_text(q)
        assert not do
        assert reason == "non_question_like"

    def test_question_like_long_text_still_repaired(self):
        q = {
            "confidence_score": 0.2,
            "is_valid": False,
            "question_type": "single_choice",
            "options": [],
            "answer": "",
            "stem": "",
            "raw_text": "1. 下列关于线性表的说法，正确的是哪一项？\nA. 线性表只能顺序存储\nB. 线性表可以链式存储\nC. 线性表不能插入元素\nD. 线性表没有逻辑结构\n解析：定义、性质、知识点如下。",
        }

        do, reason = _should_repair(q, 0.6)

        assert not _looks_like_non_question_text(q)
        assert do
        assert reason == "low_confidence"


# ============================================================
# 集成测试（mock DeepSeek API）
# ============================================================

VALID_AI_RESPONSE = {
    "question_type": "single_choice",
    "stem": "设函数 f(x) = x^2，求 f'(x)",
    "options": {"A": "2x", "B": "x", "C": "x^2", "D": "2"},
    "answer": "A",
    "analysis": "对 x^2 求导得 2x",
    "confidence": 0.9,
    "repair_actions": ["stem_cleaned", "options_structured", "answer_normalized"],
}

MULTI_CHOICE_RESPONSE = {
    "question_type": "multiple_choice",
    "stem": "下列哪些是偶数",
    "options": {"A": "2", "B": "3", "C": "4", "D": "5"},
    "answer": "A,C",
    "analysis": "2 和 4 是偶数",
    "confidence": 0.9,
    "repair_actions": ["type_detected", "answer_normalized"],
}

TF_RESPONSE = {
    "question_type": "true_false",
    "stem": "0 是自然数",
    "options": {"A": "正确", "B": "错误"},
    "answer": "T",
    "analysis": "0 是自然数",
    "confidence": 0.85,
    "repair_actions": ["answer_normalized"],
}

FILL_RESPONSE = {
    "question_type": "fill_blank",
    "stem": "x^2 的导数是 ___",
    "options": {},
    "answer": "2x",
    "analysis": "根据幂函数求导法则",
    "confidence": 0.8,
    "repair_actions": ["type_detected"],
}

SUBJECTIVE_RESPONSE = {
    "question_type": "subjective",
    "stem": "请简述导数的定义",
    "options": {},
    "answer": "函数在某点的变化率极限",
    "analysis": "导数定义为极限",
    "confidence": 0.85,
    "repair_actions": ["type_detected"],
}


def _make_question(overrides=None):
    """快速构造一个低置信度题目（会触发修复）。"""
    q = {
        "schema_version": "v1",
        "subject": "math2",
        "question_type": "single_choice",
        "stem": "",
        "options": [],
        "answer": "",
        "analysis": "",
        "raw_text": "1. 设函数 f(x) = x^2，求 f'(x)。\nA. 2x\nB. x\nC. x^2\nD. 2\n答案：A\n解析：求导得 2x",
        "knowledge_points": [],
        "difficulty": 3,
        "source": {"file": "test.pdf", "page": 1, "type": "pdf"},
        "is_valid": False,
        "errors": ["missing_stem", "missing_options", "missing_answer"],
        "warnings": [],
        "stem_hash": "abc12345",
        "confidence_score": 0.15,
    }
    if overrides:
        q.update(overrides)
    return q


def _mock_chat_response(response_dict):
    """构造 mock DeepSeek chat 返回值。"""
    import json
    return {
        "content": json.dumps(response_dict, ensure_ascii=False),
        "tokens_used": 350,
        "model": "deepseek-chat",
        "duration_ms": 800,
    }


class TestRepairQuestions:
    """集成测试：repair_questions 主函数。"""

    def _patch_deepseek(self, available=True, chat_return=None):
        """创建 mock patches。"""
        return {
            "is_available": MagicMock(return_value=available),
            "chat": AsyncMock(return_value=chat_return or _mock_chat_response(VALID_AI_RESPONSE)),
        }

    def test_repair_low_confidence_question(self):
        q = _make_question()
        mocks = self._patch_deepseek()
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 1
        assert result["stats"]["unrepaired"] == 0
        assert result["stats"]["skipped"] == 0
        repaired = result["repaired"][0]
        assert repaired["question_index"] == 0
        assert repaired["after"]["stem"] == VALID_AI_RESPONSE["stem"]
        assert repaired["after"]["answer"] == "A"
        assert repaired["after"]["question_type"] == "single_choice"
        assert len(repaired["after"]["options"]) == 4
        assert repaired["after"]["options"][0] == {"key": "A", "text": "2x"}
        assert "stem_cleaned" in repaired["repair_actions"]
        assert repaired["token_used"] == 350

    def test_high_confidence_question_skipped(self):
        q = _make_question({"confidence_score": 0.9, "is_valid": True, "stem": "long enough stem", "answer": "A", "options": [{"key": "A", "text": "2x"}], "errors": []})
        mocks = self._patch_deepseek()
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 0
        assert result["stats"]["skipped"] == 1
        assert result["skipped"][0]["reason"] == "above_threshold"

    def test_ai_repair_failure_marked_unrepaired(self):
        """AI 返回无效 JSON → unrepaired。"""
        q = _make_question()
        mocks = self._patch_deepseek(chat_return={
            "content": "sorry I can't help",
            "tokens_used": 50,
            "model": "deepseek-chat",
            "duration_ms": 200,
        })
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 0
        assert result["stats"]["unrepaired"] == 1
        assert result["unrepaired"][0]["reason"] == "ai_failed"

    def test_ai_unavailable_silent_degradation(self):
        """AI 不可用 → 全部 unrepaired，不抛异常。"""
        q = _make_question()
        mocks = self._patch_deepseek(available=False)
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 0
        assert result["stats"]["unrepaired"] == 1
        assert result["unrepaired"][0]["reason"] == "ai_unavailable"

    def test_ai_api_exception_silent_degradation(self):
        """API 抛异常 → unrepaired，不崩溃。"""
        q = _make_question()
        mocks = self._patch_deepseek()
        mocks["chat"] = AsyncMock(side_effect=RuntimeError("network error"))
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 0
        assert result["stats"]["unrepaired"] == 1
        assert result["unrepaired"][0]["reason"] == "ai_failed"

    def test_global_disabled_all_skipped(self):
        q = _make_question()
        result = asyncio.run(repair_questions([q], config={"enabled": False}))
        assert result["stats"]["repaired"] == 0
        assert result["stats"]["skipped"] == 1
        assert result["skipped"][0]["reason"] == "ai_disabled"

    def test_empty_input(self):
        result = asyncio.run(repair_questions([]))
        assert result["stats"]["total_candidates"] == 0
        assert result["repaired"] == []
        assert result["unrepaired"] == []
        assert result["skipped"] == []

    @pytest.mark.xfail(reason="AI API key not configured in CI")
    def test_mixed_questions(self):
        """混合：1 修复 + 1 跳过 + 1 修复失败。"""
        q_low = _make_question()  # 低置信度 → 修复
        q_high = _make_question({"confidence_score": 0.9, "is_valid": True, "stem": "long enough stem", "answer": "A", "options": [{"key": "A", "text": "2x"}], "errors": []})  # 跳过高置信度 → 跳过
        q_bad = _make_question({"raw_text": ""})  # 有触发但 AI 失败

        mocks = self._patch_deepseek()
        # 第一次调用返回成功，第二次调用返回失败
        mocks["chat"] = AsyncMock(side_effect=[
            _mock_chat_response(VALID_AI_RESPONSE),
            _mock_chat_response({"stem": "", "question_type": "unknown", "confidence": 0}),  # invalid
        ])

        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q_low, q_high, q_bad]))

        assert result["stats"]["repaired"] == 1
        assert result["stats"]["skipped"] == 1
        assert result["stats"]["unrepaired"] == 1

    def test_multiple_choice_repair(self):
        q = _make_question()
        mocks = self._patch_deepseek(chat_return=_mock_chat_response(MULTI_CHOICE_RESPONSE))
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 1
        after = result["repaired"][0]["after"]
        assert after["question_type"] == "multiple_choice"
        assert after["answer"] == "A,C"

    def test_true_false_repair(self):
        q = _make_question()
        mocks = self._patch_deepseek(chat_return=_mock_chat_response(TF_RESPONSE))
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 1
        after = result["repaired"][0]["after"]
        assert after["question_type"] == "true_false"
        assert after["answer"] == "T"

    def test_fill_blank_repair(self):
        q = _make_question()
        mocks = self._patch_deepseek(chat_return=_mock_chat_response(FILL_RESPONSE))
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 1
        after = result["repaired"][0]["after"]
        assert after["question_type"] == "fill_blank"

    def test_subjective_repair(self):
        q = _make_question()
        mocks = self._patch_deepseek(chat_return=_mock_chat_response(SUBJECTIVE_RESPONSE))
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        assert result["stats"]["repaired"] == 1
        after = result["repaired"][0]["after"]
        assert after["question_type"] == "subjective"

    def test_token_usage_tracked(self):
        q1 = _make_question()
        q2 = _make_question()
        mocks = self._patch_deepseek(chat_return=_mock_chat_response(VALID_AI_RESPONSE))
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q1, q2]))

        assert result["stats"]["total_tokens"] == 700  # 350 * 2

    def test_before_after_comparison(self):
        q = _make_question()
        mocks = self._patch_deepseek()
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        repaired = result["repaired"][0]
        assert repaired["before"]["is_valid"] is False
        assert repaired["after"]["is_valid"] is True
        assert repaired["before"]["confidence_score"] == 0.15
        assert repaired["after"]["confidence_score"] == 0.9
        assert repaired["before"]["errors"] == ["missing_stem", "missing_options", "missing_answer"]
        assert repaired["after"]["errors"] == []

    def test_config_threshold_respected(self):
        """自定义阈值 0.4：0.45 被跳过（需同时满足其他条件不触发）。"""
        q = _make_question({
            "confidence_score": 0.45, "is_valid": True,
            "stem": "long enough stem", "answer": "text",
            "options": [{"key": "A", "text": "2x"}], "question_type": "subjective",
        })
        mocks = self._patch_deepseek()
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]):
            result = asyncio.run(repair_questions([q], config={"confidence_threshold": 0.4}))
        assert result["stats"]["skipped"] == 1

    def test_source_info_preserved(self):
        q = _make_question()
        mocks = self._patch_deepseek()
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        after = result["repaired"][0]["after"]
        assert after["source"] == {"file": "test.pdf", "page": 1, "type": "pdf"}
        assert after["subject"] == "math2"

    def test_repair_actions_recorded(self):
        q = _make_question()
        mocks = self._patch_deepseek()
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        actions = result["repaired"][0]["repair_actions"]
        assert isinstance(actions, list)
        assert len(actions) > 0


class TestTokenLimit:
    """Token 限额控制测试。"""

    def test_token_limit_allows_when_under(self):
        import app.features.ai_repair as mod
        mod._token_usage["daily"] = 0
        mod._token_usage["monthly"] = 0
        assert _check_token_limit(500, {"daily_token_limit": 1000, "monthly_token_limit": 10000})

    def test_token_limit_blocks_when_daily_exceeded(self):
        import app.features.ai_repair as mod
        mod._token_usage["daily"] = 900
        mod._token_usage["monthly"] = 0
        assert not _check_token_limit(200, {"daily_token_limit": 1000, "monthly_token_limit": 10000})

    def test_token_limit_blocks_when_monthly_exceeded(self):
        import app.features.ai_repair as mod
        mod._token_usage["daily"] = 0
        mod._token_usage["monthly"] = 9500
        assert not _check_token_limit(1000, {"daily_token_limit": 100000, "monthly_token_limit": 10000})

    def test_record_token_usage(self):
        import app.features.ai_repair as mod
        mod._token_usage["daily"] = 100
        mod._token_usage["monthly"] = 500
        _record_token_usage(50)
        assert mod._token_usage["daily"] == 150
        assert mod._token_usage["monthly"] == 550

    def test_repair_skipped_when_limit_exceeded(self):
        """token 超限 → AI 返回 None → unrepaired。"""
        import app.features.ai_repair as mod
        q = _make_question()
        # 模拟超限
        mod._token_usage["daily"] = 99900
        mod._token_usage["monthly"] = 0

        mocks = {
            "is_available": MagicMock(return_value=True),
            "chat": AsyncMock(return_value=_mock_chat_response(VALID_AI_RESPONSE)),
        }
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q], config={"daily_token_limit": 100000, "monthly_token_limit": 2000000}))

        assert result["stats"]["unrepaired"] >= 1
