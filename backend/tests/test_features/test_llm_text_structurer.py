"""LLM 文本结构化层测试 — features/llm_text_structurer.py"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.features import llm_text_structurer as mod


@pytest.fixture(autouse=True)
def _reset_llm_state():
    """每个测试前清理 token 预算 + 启用 feature flag。"""
    mod._reset_budget_for_test()
    original_flag = settings.TEXT_IMPORT_LLM_ENABLED
    original_budget = settings.TEXT_IMPORT_LLM_DAILY_TOKEN
    settings.TEXT_IMPORT_LLM_ENABLED = True
    settings.TEXT_IMPORT_LLM_DAILY_TOKEN = 100_000
    yield
    settings.TEXT_IMPORT_LLM_ENABLED = original_flag
    settings.TEXT_IMPORT_LLM_DAILY_TOKEN = original_budget


# ============================================================
# should_call_llm 触发条件
# ============================================================


class TestShouldCallLlm:
    def test_disabled_returns_false(self):
        settings.TEXT_IMPORT_LLM_ENABLED = False
        ok, reason = mod.should_call_llm("某题？\nA.a\nB.b\n答案:A", {"stem": "x", "options": [1, 2]})
        assert not ok
        assert reason == "feature_disabled"

    def test_block_too_short_skipped(self):
        ok, reason = mod.should_call_llm("xx", {"stem": "xx"})
        assert not ok
        assert reason == "block_too_short"

    def test_block_too_long_skipped(self):
        long_text = "x" * (settings.TEXT_IMPORT_LLM_MAX_BLOCK_CHARS + 1)
        ok, reason = mod.should_call_llm(long_text, {"stem": "x"})
        assert not ok
        assert reason == "block_too_long"

    def test_stem_empty_triggers(self):
        block = "A. opt1\nB. opt2\n答案: A"
        ok, reason = mod.should_call_llm(block, {"stem": "", "options": [], "answer": ""})
        assert ok
        assert reason == "stem_empty"

    def test_options_underdetected_triggers(self):
        block = "题干？\nA. 选项一\nB. 选项二\nC. 选项三\n答案: A"
        parsed = {
            "stem": "题干？",
            "options": [{"key": "A", "text": "选项一"}],  # 仅 1 个但原文有 3+
            "answer": "A",
            "question_type": "single_choice",
            "detection_method": "heuristic",
        }
        ok, reason = mod.should_call_llm(block, parsed)
        assert ok
        assert reason == "options_underdetected"

    def test_answer_label_unparsed_triggers(self):
        block = "题干？\nA. a\nB. b\nC. c\nD. d\n参考答案：D"
        parsed = {
            "stem": "题干？",
            "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
            "answer": "",
            "question_type": "single_choice",
            "detection_method": "heuristic",
        }
        ok, reason = mod.should_call_llm(block, parsed)
        assert ok
        assert reason == "answer_label_unparsed"

    def test_single_line_flattened_triggers(self):
        # 故意不含"答案"标签，避免与 answer_label_unparsed 触发冲突；
        # 文本需 ≥ 100 字符以匹配单行压平阈值
        block = (
            "下列关于二叉树高度N的描述中，从根结点到任意叶子结点的最长路径上的结点数为高度。"
            "A. 二叉树的高度为logN B. 二叉树高度为N C. 满二叉树叶子数为(N+1)/2 "
            "D. 完全二叉树高度为logN+1"
        )
        parsed = {
            "stem": block,
            "options": [],
            "answer": "D",
            "question_type": "subjective",
            "detection_method": "heuristic",
        }
        ok, reason = mod.should_call_llm(block, parsed)
        assert ok
        assert reason == "single_line_flattened"

    def test_multi_blank_misdetected_triggers(self):
        block = "下列空白处填入( )和( )正确的是？\nA. a\n答案:A"
        parsed = {
            "stem": "下列空白处填入( )和( )正确的是？",
            "options": [{"key": "A", "text": "a"}],
            "answer": "A",
            "question_type": "single_choice",
            "detection_method": "heuristic",
        }
        ok, reason = mod.should_call_llm(block, parsed)
        assert ok
        assert reason == "multi_blank_misdetected"

    def test_well_parsed_block_skipped(self):
        block = "题干？\nA. a\nB. b\nC. c\nD. d\n答案: A"
        parsed = {
            "stem": "题干？",
            "options": [
                {"key": "A", "text": "a"}, {"key": "B", "text": "b"},
                {"key": "C", "text": "c"}, {"key": "D", "text": "d"},
            ],
            "answer": "A",
            "question_type": "single_choice",
            "detection_method": "labeled",
        }
        ok, reason = mod.should_call_llm(block, parsed)
        assert not ok
        assert reason == "rule_ok"


# ============================================================
# 反幻觉守门
# ============================================================


class TestHallucinationGuard:
    def test_clean_passes_when_all_in_source(self):
        original = "题干内容很丰富。\nA. 选项一\nB. 选项二\n答案：A\n解析：因为A正确。"
        structured = {
            "stem": "题干内容很丰富。",
            "question_type": "single_choice",
            "options": [{"key": "A", "text": "选项一"}, {"key": "B", "text": "选项二"}],
            "answer": "A",
            "analysis": "因为A正确。",
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["stem"] == "题干内容很丰富。"
        assert len(cleaned["options"]) == 2
        assert cleaned["answer"] == "A"
        assert cleaned["analysis"] == "因为A正确。"
        assert dropped == []

    def test_drops_fabricated_stem(self):
        original = "A. a\nB. b\n答案：A"
        structured = {
            "stem": "我编造的全新题干内容根本不在原文中存在",
            "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
            "answer": "A",
            "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["stem"] is None
        assert "stem" in dropped
        assert cleaned["answer"] == "A"

    def test_drops_fabricated_option(self):
        original = "题干？\nA. 真实选项\n答案: A"
        structured = {
            "stem": "题干？",
            "options": [
                {"key": "A", "text": "真实选项"},
                {"key": "B", "text": "我编造的虚假选项内容"},
            ],
            "answer": "A",
            "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert len(cleaned["options"]) == 1
        assert cleaned["options"][0]["key"] == "A"
        assert "option_B" in dropped

    def test_drops_fabricated_analysis(self):
        original = "题干？\nA. a\nB. b\n答案：A"
        structured = {
            "stem": "题干？",
            "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
            "answer": "A",
            "analysis": "因为根据某个完全不存在于原文的定理推导出来A是正确的",
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["analysis"] is None
        assert "analysis" in dropped

    def test_letter_answer_passes_when_signal_in_source(self):
        # 原文有答案标签，字母答案放宽通过
        original = "题干？\nA. a\nB. b\n答案：C"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "C", "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] == "C"

    def test_letter_answer_passes_with_trailing_standalone_letter(self):
        # 原文末尾独立单字母也算答案信号
        original = "题干？\nA. a\nB. b\n\nC"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "C", "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] == "C"

    def test_letter_answer_dropped_when_no_signal_in_source(self):
        # 原文没有任何答案信号 → LLM 输出的字母答案应被拦截
        original = "下列哪个是正确的？\nA. 选项甲\nB. 选项乙\nC. 选项丙\nD. 选项丁"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "B", "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] is None
        assert "answer" in dropped

    def test_multi_letter_answer_dropped_when_no_signal(self):
        original = "下列哪些正确？\nA. a\nB. b\nC. c\nD. d"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": ["A", "C"], "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] is None
        assert "answer" in dropped

    def test_letter_answer_dropped_when_does_not_match_source(self):
        # 原文答案是 D，LLM 输出 C → 必须拦截（核心反幻觉场景）
        original = "题干？\nA. a\nB. b\nC. c\nD. d\n参考答案：D"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "C", "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] is None
        assert "answer" in dropped

    def test_letter_answer_passes_when_matches_label(self):
        # 原文 "参考答案：D"，LLM 输出 D → 通过
        original = "题干？\nA. a\nB. b\n参考答案：D"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "D", "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] == "D"

    def test_multi_letter_partial_mismatch_dropped(self):
        # 原文 "答案: A,C"，LLM 输出 "AB" → B 不在白名单，整体拦截
        original = "题干？\nA. a\nB. b\nC. c\n答案: A,C"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "AB", "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] is None
        assert "answer" in dropped

    def test_multi_letter_passes_when_subset_of_source(self):
        # 原文 "答案: A,B,C"，LLM 输出 ["A","C"] → 通过
        original = "题干？\nA. a\nB. b\nC. c\n答案: A,B,C"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": ["A", "C"], "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] == "A,C"

    def test_chinese_separator_in_answer_label_extracts_all(self):
        # 原文 "答案：A、C"，LLM 输出 "A,C" → 通过
        original = "题干？\nA. a\nB. b\nC. c\n答案：A、C"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "AC", "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] == "A,C"

    def test_tf_answer_dropped_without_tf_signal(self):
        # 原文只有字母答案信号、没有判断题信号，LLM 输出"正确" → 拦截
        original = "下列说法是否正确？\nA. a\nB. b\n答案：A"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "正确", "analysis": None,
        }
        cleaned, dropped = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] is None
        assert "answer" in dropped

    def test_tf_answer_passes_with_label(self):
        # 原文 "答案：正确"，LLM 输出"正确" → 通过
        original = "下列说法是否正确？\n答案：正确"
        structured = {
            "stem": None, "question_type": None,
            "options": [], "answer": "正确", "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["answer"] == "正确"

    def test_invalid_question_type_dropped(self):
        original = "题干？"
        structured = {
            "stem": "题干？",
            "question_type": "weird_type",
            "options": [],
            "answer": None,
            "analysis": None,
        }
        cleaned, _ = mod._validate_no_hallucination(structured, original)
        assert cleaned["question_type"] is None


# ============================================================
# JSON 解析
# ============================================================


class TestParseJsonResponse:
    def test_pure_json(self):
        assert mod._parse_json_response('{"a": 1}') == {"a": 1}

    def test_fenced_code_block(self):
        assert mod._parse_json_response('前缀\n```json\n{"a": 2}\n```\n后缀') == {"a": 2}

    def test_brace_extraction(self):
        assert mod._parse_json_response('解释：这是结果 {"a": 3} 完毕') == {"a": 3}

    def test_empty_returns_none(self):
        assert mod._parse_json_response("") is None

    def test_malformed_returns_none(self):
        assert mod._parse_json_response("{ not json") is None


# ============================================================
# structure_text_block 调用与降级
# ============================================================


@pytest.mark.asyncio
class TestStructureTextBlock:
    async def test_disabled_returns_none(self, monkeypatch):
        settings.TEXT_IMPORT_LLM_ENABLED = False
        result = await mod.structure_text_block("test")
        assert result is None

    async def test_unavailable_client_returns_none(self, monkeypatch):
        from app.ai import client as client_mod
        monkeypatch.setattr(client_mod.deepseek, "_api_key", "")
        result = await mod.structure_text_block("test text content")
        assert result is None

    async def test_budget_exhausted_returns_none(self, monkeypatch):
        from app.ai import client as client_mod
        monkeypatch.setattr(client_mod.deepseek, "_api_key", "sk-real")
        settings.TEXT_IMPORT_LLM_DAILY_TOKEN = 1  # 强制超限
        result = await mod.structure_text_block("题干？\nA. a\nB. b\n答案: A")
        assert result is None

    async def test_llm_call_failure_returns_none(self, monkeypatch):
        from app.ai import client as client_mod
        monkeypatch.setattr(client_mod.deepseek, "_api_key", "sk-real")
        async def _raise(*a, **kw):
            raise RuntimeError("network down")
        monkeypatch.setattr(client_mod.deepseek, "chat", _raise)
        result = await mod.structure_text_block("题干？\nA. a\nB. b\n答案: A")
        assert result is None

    async def test_successful_structure_with_clean_output(self, monkeypatch):
        from app.ai import client as client_mod
        monkeypatch.setattr(client_mod.deepseek, "_api_key", "sk-real")
        original = "题干？\nA. 选项A\nB. 选项B\n答案：B"
        async def _fake_chat(*a, **kw):
            return {
                "content": (
                    '{"stem": "题干？", "question_type": "single_choice", '
                    '"options": [{"key":"A","text":"选项A"},{"key":"B","text":"选项B"}], '
                    '"answer": "B", "analysis": null}'
                ),
                "tokens_used": 100,
                "model": "deepseek-chat",
                "duration_ms": 200,
            }
        monkeypatch.setattr(client_mod.deepseek, "chat", _fake_chat)
        result = await mod.structure_text_block(original)
        assert result is not None
        assert result["stem"] == "题干？"
        assert result["answer"] == "B"
        assert len(result["options"]) == 2
        assert result["analysis"] is None
        assert result["_dropped"] == []

    async def test_all_fields_dropped_returns_none(self, monkeypatch):
        from app.ai import client as client_mod
        monkeypatch.setattr(client_mod.deepseek, "_api_key", "sk-real")
        original = "短"  # 不会触发 should_call_llm 的真实路径，但模块允许直接调用
        async def _fake_chat(*a, **kw):
            return {
                "content": '{"stem": "捏造内容", "options": [{"key":"X","text":"虚假"}], "answer": null}',
                "tokens_used": 50,
                "model": "deepseek-chat",
                "duration_ms": 100,
            }
        monkeypatch.setattr(client_mod.deepseek, "chat", _fake_chat)
        result = await mod.structure_text_block(original)
        assert result is None


# ============================================================
# parse_text_questions_async 集成
# ============================================================


@pytest.mark.asyncio
class TestParseAsyncIntegration:
    async def test_well_formed_text_does_not_call_llm(self, monkeypatch):
        from app.features import text_question_parser
        from app.features import llm_text_structurer

        called = {"count": 0}
        async def _fake(*a, **kw):
            called["count"] += 1
            return None
        monkeypatch.setattr(llm_text_structurer, "structure_text_block", _fake)

        text = "题干？\nA. a\nB. b\nC. c\nD. d\n答案: A"
        result = await text_question_parser.parse_text_questions_async(text, subject="exam408")

        assert result["raw_count"] == 1
        assert called["count"] == 0  # 规则解析成功，不应触发 LLM

    async def test_low_confidence_triggers_llm_and_merges(self, monkeypatch):
        from app.features import text_question_parser
        from app.features import llm_text_structurer

        # 单行压平：题干 + 选项 + 答案全在一行
        flattened = (
            "下列关于二叉树高度的描述，正确的是？A. 高度等于logN B. 高度等于N "
            "C. 高度至多为N-1 D. 高度恰好为N-1 答案: C"
        )

        async def _fake(block_text, rule_hint=None):
            assert "二叉树" in block_text
            return {
                "stem": "下列关于二叉树高度的描述，正确的是？",
                "question_type": "single_choice",
                "options": [
                    {"key": "A", "text": "高度等于logN"},
                    {"key": "B", "text": "高度等于N"},
                    {"key": "C", "text": "高度至多为N-1"},
                    {"key": "D", "text": "高度恰好为N-1"},
                ],
                "answer": "C",
                "analysis": None,
                "_dropped": [],
                "_tokens": 200,
            }
        monkeypatch.setattr(llm_text_structurer, "structure_text_block", _fake)

        result = await text_question_parser.parse_text_questions_async(flattened, subject="exam408")
        assert result["raw_count"] == 1
        q = result["questions"][0]
        assert q["detection_method"] == "llm_structured"
        assert "二叉树" in q["stem"]
        assert len(q["options"]) == 4
        assert q["answer"] == "C"
        assert q["question_type"] == "single_choice"
        assert q["is_valid"]

    async def test_llm_failure_falls_back_to_rule_result(self, monkeypatch):
        from app.features import text_question_parser
        from app.features import llm_text_structurer

        async def _fake(*a, **kw):
            return None  # 模拟降级
        monkeypatch.setattr(llm_text_structurer, "structure_text_block", _fake)

        flattened = (
            "下列关于二叉树高度的描述，正确的是？A. 高度等于logN B. 高度等于N "
            "C. 高度至多为N-1 D. 高度恰好为N-1 答案: C"
        )
        result = await text_question_parser.parse_text_questions_async(flattened, subject="exam408")
        # 规则解析器有自己的尝试结果，LLM 失败后保留之
        assert result["raw_count"] == 1
        q = result["questions"][0]
        assert "llm_failed" in q["detection_method"]

    async def test_llm_fabricated_analysis_blocked_by_guard(self, monkeypatch):
        """LLM 输出捏造的解析应被反幻觉守门拦截，最终 analysis 为空。"""
        from app.features import text_question_parser
        from app.features import llm_text_structurer

        # 单行压平 + 含答案标签场景，确保 LLM 兜底被触发
        block = (
            "下列关于二叉树高度N的描述中，从根到叶子的最长路径长度即为高度。"
            "A. 二叉树高度为logN B. 二叉树高度为N C. 满二叉树叶子数为(N+1)/2 "
            "D. 完全二叉树高度为logN+1 答案: D"
        )

        async def _llm_with_fabricated_analysis(block_text, rule_hint=None):
            from app.features.llm_text_structurer import _validate_no_hallucination
            cleaned, dropped = _validate_no_hallucination({
                "stem": "下列关于二叉树高度N的描述中，从根到叶子的最长路径长度即为高度。",
                "question_type": "single_choice",
                "options": [
                    {"key": "A", "text": "二叉树高度为logN"},
                    {"key": "B", "text": "二叉树高度为N"},
                    {"key": "C", "text": "满二叉树叶子数为(N+1)/2"},
                    {"key": "D", "text": "完全二叉树高度为logN+1"},
                ],
                "answer": "D",
                # 完全捏造的解析（原文中没有任何解析内容）
                "analysis": "根据二叉树性质中的某条不存在的定理，可以推出D是最严格的上界",
            }, block_text)
            cleaned["_dropped"] = dropped
            cleaned["_tokens"] = 200
            return cleaned

        monkeypatch.setattr(llm_text_structurer, "structure_text_block", _llm_with_fabricated_analysis)
        result = await text_question_parser.parse_text_questions_async(block, subject="exam408")
        q = result["questions"][0]
        assert q["detection_method"] == "llm_structured"
        assert q["answer"] == "D"
        # 捏造的解析必须被反幻觉守门拦截
        assert not q["analysis"]
        # 守门移除字段应记入 warnings
        assert any("LLM 输出字段 analysis 未通过反幻觉校验" in w for w in result["warnings"])
