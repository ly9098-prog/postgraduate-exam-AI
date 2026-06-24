"""选项丢失防御测试 — 确保 options 永远不会被 pipeline 任何层吞掉。

核心不变式（必须始终成立）：
    detect_options_from_text(raw_text) == True
    ⇒ parsed_options / options 不允许为 None 或 []

如果违反，说明 pipeline 某层（classifier / split / freeze / normalize）
存在静默丢弃 options 的 bug。
"""

import pytest

pytestmark = pytest.mark.options_pipeline

from app.features.question_type_classifier import (
    detect_options_from_text,
    extract_options_from_text,
    force_options_probe,
)
from app.features.question_normalizer import normalize_question as _normalize_question

QT_SINGLE_CHOICE = "single_choice"
QT_SUBJECTIVE = "subjective"


# =========================================================================
# 不变式：detect_options_from_text=True ⇒ extract_options_from_text 非空
# =========================================================================

class TestInvariantExtractNonEmpty:
    """核心不变式：detect=True ⇒ extract 返回非空 dict。"""

    def test_standard_abcd(self):
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        assert detect_options_from_text(text) is True
        opts = extract_options_from_text(text)
        assert len(opts) >= 2, f"应至少提取 2 个选项, 实际: {opts}"

    def test_abcd_with_code_block(self):
        """代码块 + A/B/C/D → 不丢失。"""
        text = (
            "设栈初始为空，出栈序列不可能的是？\n"
            "```\n"
            "int stack[10];\n"
            "```\n"
            "A. 1,2,3,4,5\n"
            "B. 5,4,3,2,1\n"
            "C. 4,3,2,1,5\n"
            "D. 3,2,1,5,4"
        )
        assert detect_options_from_text(text) is True
        opts = extract_options_from_text(text)
        assert len(opts) == 4, f"应提取 4 个选项, 实际: {opts}"
        assert "A" in opts and "B" in opts and "C" in opts and "D" in opts

    def test_inline_after_code(self):
        """代码行后行内选项。"""
        text = "int x = 1;  A. 输出1  B. 输出2  C. 输出3  D. 输出4"
        assert detect_options_from_text(text) is True
        opts = extract_options_from_text(text)
        assert len(opts) >= 2, f"行内选项不应丢失: {opts}"

    def test_fragmented_ocr(self):
        """断裂 OCR：A．和内容被换行隔开。"""
        text = "下列正确的是？\nA．\n值1\nB．\n值2\nC．\n值3\nD．\n值4"
        assert detect_options_from_text(text) is True
        opts = extract_options_from_text(text)
        # 断裂 OCR 时 extract 至少提取到部分即可
        assert len(opts) >= 2, f"断裂 OCR 不应丢选项: {opts}"

    def test_no_options_returns_empty(self):
        """纯代码题（无选项）→ extract 返回空。"""
        text = (
            "请写出以下代码的输出结果：\n"
            "```c\n"
            "int main() { return 0; }\n"
            "```"
        )
        assert detect_options_from_text(text) is False
        opts = extract_options_from_text(text)
        assert opts == {}

    def test_circled_digits(self):
        """①②③④ 圈号 → 不丢失。"""
        text = "下列正确的是？\n① 甲\n② 乙\n③ 丙\n④ 丁"
        assert detect_options_from_text(text) is True
        opts = extract_options_from_text(text)
        assert len(opts) >= 2, f"圈号选项不应丢失: {opts}"

    def test_broad_format_ocr(self):
        """宽格式 OCR：'A  xxx'（无点号但字母+空格+内容）。"""
        text = "选择正确的是\nA  选项一\nB  选项二\nC  选项三\nD  选项四"
        assert detect_options_from_text(text) is True
        opts = extract_options_from_text(text)
        assert len(opts) >= 2, f"宽格式不应丢选项: {opts}"


# =========================================================================
# Pipeline 级防御：normalize_question 不丢选项
# =========================================================================

class TestPipelineOptionsNeverDropped:
    """normalize_question 管道中选项不应被丢弃。"""

    def _run(self, raw_text: str, option_lines: dict | None = None,
             has_options: bool = False, answer: str = "A") -> dict:
        raw = {
            "number": 1,
            "raw_question_text": raw_text,
            "page_start": 1,
            "page_end": 1,
            "has_options": has_options,
            "option_lines": option_lines or {},
            "confidence": 0.7,
        }
        matched = {"question_number": 1, "answer": answer}
        return _normalize_question(raw, matched)

    def test_standard_options_preserved(self):
        """标准 A/B/C/D 永远不会被 drop。"""
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        result = self._run(text, answer="A")
        assert result["options_classified"] is True, (
            f"classifier 应判定 has_options=True: {result.get('options_classify_reason')}"
        )
        assert len(result["options"]) >= 2, (
            f"options 不应为空: {result['options']}"
        )
        assert result["question_type"] == QT_SINGLE_CHOICE

    def test_code_and_options_preserved(self):
        """BUGS 案例一：代码块+选项 → options 不丢失。"""
        text = (
            "设栈初始为空，出栈序列不可能的是？\n"
            "```\n"
            "int stack[10];\n"
            "```\n"
            "A. 1,2,3,4,5\n"
            "B. 5,4,3,2,1\n"
            "C. 4,3,2,1,5\n"
            "D. 3,2,1,5,4"
        )
        # 模拟 splitter 失败：option_lines 为空
        result = self._run(text, option_lines={}, has_options=False, answer="D")
        assert result["options_classified"] is True, (
            f"代码+选项场景 classifier 应返回 True: {result.get('options_classify_reason')}"
        )
        assert len(result["options"]) == 4, (
            f"代码+选项场景不应丢选项: {result['options']}"
        )
        assert result["question_type"] == QT_SINGLE_CHOICE

    def test_pure_code_no_options_stays_empty(self):
        """纯代码题（无选项）→ options 保持空。"""
        text = (
            "请写出以下代码的输出结果：\n"
            "```c\n"
            "int main() { return 0; }\n"
            "```"
        )
        result = self._run(text, option_lines={}, has_options=False, answer="")
        assert len(result["options"]) == 0, f"纯代码题 options 应为空: {result['options']}"
        assert result["question_type"] == QT_SUBJECTIVE

    def test_ocr_damaged_but_structure_preserved(self):
        """OCR 有损坏但 A./B./C./D. 结构可辨认 → 不丢。"""
        text = (
            "下列哪个是偶数？\n"
            "A.2\n"       # 无空格（紧凑OCR）
            "B．4\n"      # 全角点
            "C:6\n"       # 冒号
            "D)8"         # 括号
        )
        result = self._run(text, option_lines={}, has_options=False, answer="A")
        assert result["options_classified"] is True
        assert len(result["options"]) >= 2, (
            f"结构可辨认时不应丢选项: {result['options']}"
        )

    def test_options_with_subjective_type_override(self):
        """即使上游标记 subjective，检测到选项后强制 single_choice。"""
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        raw = {
            "number": 1,
            "raw_question_text": text,
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.5,
            "section_type": "question_type_subjective",
        }
        matched = {"question_number": 1, "answer": "A"}
        result = _normalize_question(raw, matched)
        assert result["options_classified"] is True
        assert result["question_type"] == QT_SINGLE_CHOICE, (
            f"检测到选项后应覆盖 subjective: {result['question_type']}"
        )
        assert len(result["options"]) >= 2


# =========================================================================
# SSOT 唯一性验证
# =========================================================================

class TestSsotUniqueness:
    """验证 extract_options_from_text 是唯一的 fallback 入口。"""

    def test_normalizer_delegates_to_ssot(self):
        """normalize_question 的选项提取委托至 extract_options_from_text。

        验证 normalizer 在 option_lines 为空、classifier 判定有选项时，
        从 SSOT 提取的结果与直接调用 extract_options_from_text 一致。
        """
        text = "A. 甲\nB. 乙\nC. 丙\nD. 丁"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "option_lines": {},
             "page_start": 1, "page_end": 1, "has_options": False, "confidence": 0.7},
            {"question_number": 1, "answer": "A"},
        )
        ssot_opts = extract_options_from_text(text)
        result_opts = {o["key"]: o["text"] for o in result.get("options", [])}
        assert result_opts == ssot_opts, (
            f"normalizer options({result_opts}) 应与 SSOT({ssot_opts}) 一致"
        )

    def test_scan_entire_block_delegates_to_ssot(self):
        """scan_entire_block 委托至 extract_options_from_text。"""
        from app.features.question_splitter import scan_entire_block_including_surrounding_lines as scan
        from app.features.question_type_classifier import extract_options_from_text as ssot

        text = "A. 甲\nB. 乙\nC. 丙\nD. 丁"
        result_scan = scan(text)
        result_ssot = ssot(text)
        assert result_scan == result_ssot, (
            f"scan({result_scan}) 应与 SSOT({result_ssot}) 一致"
        )


# =========================================================================
# 回归：被修复的 BUGS 案例
# =========================================================================

class TestBugsCasesFixed:
    """已修复的 BUGS 案例回归验证。"""

    def test_bugs_case1_code_stack_options(self):
        """BUGS 案例一：顺序栈代码题 + A/B/C/D → parsed_options == 4 个。"""
        text = (
            "设栈的初始状态为空，元素1,2,3,4,5依次入栈，"
            "则出栈序列不可能的是？\n"
            "```\n"
            "# 栈的初始状态\n"
            "stack = []\n"
            "```\n"
            "A. 1,2,3,4,5\n"
            "B. 5,4,3,2,1\n"
            "C. 4,3,2,1,5\n"
            "D. 3,2,1,5,4"
        )
        raw = {
            "number": 1,
            "raw_question_text": text,
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.7,
        }
        matched = {"question_number": 1, "answer": "D"}
        result = _normalize_question(raw, matched)

        assert result["options_classified"] is True, "classifier 必须判定 has_options=True"
        assert len(result["options"]) == 4, (
            f"必须提取 4 个选项, 实际: {len(result['options'])} -> {result['options']}"
        )
        assert result["question_type"] == QT_SINGLE_CHOICE, (
            f"题型应为 single_choice, 实际: {result['question_type']}"
        )
        # BUGS 案例的验收标准
        assert result["is_valid"] is True


# =========================================================================
# OPTIONS-ENFORCEMENT: orchestrator post-stage 验证
# =========================================================================

class TestOptionsEnforcement:
    """模拟 pipeline_orchestrator 的 OPTIONS-ENFORCEMENT post-stage。

    enforce 规则：
        detect_options_from_text(raw_text) == True
        但 q.options 为空 → 打 risk_flag="options_dropped_enforcement"

    验证 normalizer 输出永远不会触发此告警（不应有假阳性）。
    同时也验证：如果未来某层错误丢弃了选项，enforcement 能正确捕获。
    """

    def _simulate_enforcement(self, question: dict) -> list[str]:
        """模拟 orchestrator 的 enforce 逻辑，返回触发的 risk_flags。

        blank_option_groups 豁免：多空选择题的 top-level options 设计为空，
        选项存储在 blank_option_groups 中，不应触发 enforce。
        """
        if question.get("blank_option_groups"):
            return []
        raw_text = question.get("raw_text") or question.get("raw_question_text", "")
        if not raw_text:
            return []
        if not detect_options_from_text(raw_text):
            return []
        opts = question.get("options", [])
        if opts:
            return []
        return ["options_dropped_enforcement"]

    def test_normal_question_no_false_positive(self):
        """标准选择题 → enforce 不应触发。"""
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "option_lines": {}, "page_start": 1, "page_end": 1,
             "has_options": False, "confidence": 0.7},
            {"question_number": 1, "answer": "A"},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"不应触发 enforce: {flags}"

    def test_subjective_no_false_positive(self):
        """主观题 → enforce 不应触发。"""
        text = "请简述 TCP 三次握手的过程。"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "option_lines": {}, "page_start": 1, "page_end": 1,
             "has_options": False, "confidence": 0.7},
            {"question_number": 1, "answer": ""},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"主观题不应触发 enforce: {flags}"

    def test_code_no_options_no_false_positive(self):
        """纯代码题无选项 → enforce 不应触发。"""
        text = "请写出以下代码的输出结果：\n```c\nint main() { return 0; }\n```"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "option_lines": {}, "page_start": 1, "page_end": 1,
             "has_options": False, "confidence": 0.7},
            {"question_number": 1, "answer": ""},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"无选项代码题不应触发 enforce: {flags}"

    def test_code_with_options_no_false_positive(self):
        """代码题 + A/B/C/D → enforce 不应触发。"""
        text = ("设栈初始为空，出栈序列不可能的是？\n```\nint stack[10];\n```\n"
                "A. 1,2,3,4,5\nB. 5,4,3,2,1\nC. 4,3,2,1,5\nD. 3,2,1,5,4")
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "option_lines": {}, "page_start": 1, "page_end": 1,
             "has_options": False, "confidence": 0.7},
            {"question_number": 1, "answer": "D"},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"代码+选项不应触发 enforce: {flags}"
        assert len(result.get("options", [])) == 4, "选项不应被丢弃"

    def test_frozen_no_false_positive(self):
        """冻结题目 → enforce 不应触发。"""
        text = "冻结题\nA. 旧\nB. 的\nC. 选\nD. 项"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "page_start": 1, "page_end": 1,
             "has_options": True, "confidence": 1.0, "is_frozen": True,
             "option_lines": {"A": "旧", "B": "的", "C": "选", "D": "项"}},
            {"question_number": 1, "answer": "A"},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"冻结题不应触发 enforce: {flags}"
        assert len(result.get("options", [])) == 4, "冻结选项不应被丢弃"

    def test_blank_option_groups_no_false_positive(self):
        """多空选择题 → enforce 不应触发。"""
        text = "多空选择题\n① A. 甲 B. 乙\n② A. 丙 B. 丁"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "page_start": 1, "page_end": 1,
             "has_options": True, "confidence": 0.7,
             "option_lines": {},
             "blank_option_groups": [
                 {"id": "①", "options": {"A": "甲", "B": "乙"}},
                 {"id": "②", "options": {"A": "丙", "B": "丁"}},
             ]},
            {"question_number": 1, "answer": "A"},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"多空选择不应触发 enforce: {flags}"

    def test_simulate_dropped_options_triggers_enforce(self):
        """模拟选项被丢弃 → enforce 正确触发。"""
        # 文本有 A/B/C/D，但人为设置空 options 模拟 pipeline bug
        text = "被丢弃的选项题\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        # 直接构造一个有 detect=True 但 options=[] 的 question
        question = {
            "raw_question_text": text,
            "options": [],
            "number": 1,
        }
        flags = self._simulate_enforcement(question)
        assert "options_dropped_enforcement" in flags, (
            f"选项被丢弃时应触发 enforce: {flags}"
        )

    def test_fragmented_ocr_no_false_positive(self):
        """断裂 OCR → 结构可辨认时不触发 enforce。"""
        text = "下列正确的是？\nA．\n值1\nB．\n值2\nC．\n值3\nD．\n值4"
        result = _normalize_question(
            {"number": 1, "raw_question_text": text, "option_lines": {}, "page_start": 1, "page_end": 1,
             "has_options": False, "confidence": 0.7},
            {"question_number": 1, "answer": "A"},
        )
        flags = self._simulate_enforcement(result)
        assert not flags, f"断裂 OCR 不应触发 enforce: {flags}"
        # 至少提取到部分选项
        assert len(result.get("options", [])) >= 1, "断裂 OCR 应提取至少 1 个选项"


# =========================================================================
# Force Options Probe (debug-only diagnostic)
# =========================================================================

class TestForceOptionsProbe:
    """验证 force_options_probe 在各种输入下的行为。"""

    def test_standard_abcd_detected(self):
        """标准 A/B/C/D → detected=True。"""
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        result = force_options_probe(text)
        assert result["detected"] is True
        assert result["extract_ok"] is True
        assert "strict_line_abcd" in result["patterns"]

    def test_no_options_not_detected(self):
        """纯代码题（无选项）→ detected=False。"""
        text = "请写出以下代码的输出结果：\n```c\nint main() { return 0; }\n```"
        result = force_options_probe(text)
        assert result["detected"] is False
        assert result["extract_ok"] is False
        assert len(result["total_unique_abcd_keys"]) == 0

    def test_fragmented_ocr_detected(self):
        """断裂 OCR 选项 → 至少一个 pattern 匹配。"""
        text = "下列正确的是？\nA．．值1\nB．．值2\nC．．值3\nD．．值4"
        result = force_options_probe(text)
        assert result["detected"] is True

    def test_circled_digits_detected(self):
        """圈号选项 → detected=True。"""
        text = "下列正确的是？\n① 甲\n② 乙\n③ 丙\n④ 丁"
        result = force_options_probe(text)
        assert result["detected"] is True
        assert result["patterns"]["circled"]["matched"] is True

    def test_code_and_options_detected(self):
        """BUGS 案例：代码块+选项 → detected=True。"""
        text = ("设栈初始为空，出栈序列不可能的是？\n```\nint stack[10];\n```\n"
                "A. 1,2,3,4,5\nB. 5,4,3,2,1\nC. 4,3,2,1,5\nD. 3,2,1,5,4")
        result = force_options_probe(text)
        assert result["detected"] is True
        assert result["extract_ok"] is True
        assert len(result["extracted"]) == 4

    def test_probe_versus_detect_agreement(self):
        """force_options_probe.detected 应与 detect_options_from_text 一致。"""
        cases = [
            "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁",
            "纯代码题",
            "下列正确的是？\n① 甲\n② 乙\n③ 丙\n④ 丁",
            ("设栈初始为空\n```\nint x;\n```\n"
             "A. 1\nB. 2\nC. 3\nD. 4"),
        ]
        for text in cases:
            probe = force_options_probe(text)
            detect = detect_options_from_text(text)
            assert probe["detected"] == detect, (
                f"不一致: text={text[:50]}, probe={probe['detected']}, detect={detect}"
            )

    def test_probe_all_patterns_reported(self):
        """force_options_probe 应报告所有 7 种 pattern 的结果。"""
        text = "测试文本"
        result = force_options_probe(text)
        expected_patterns = {
            "strict_line_abcd", "inline_abcd", "numbered_choice",
            "circled", "choice_keywords", "fragmented_ocr", "broad_format",
        }
        assert expected_patterns.issubset(result["patterns"].keys()), (
            f"缺少 pattern: {expected_patterns - set(result['patterns'].keys())}"
        )
        assert "summary" in result
        assert "extracted" in result

    def test_empty_text(self):
        """空文本 → detected=False。"""
        result = force_options_probe("")
        assert result["detected"] is False
        assert result["summary"] == "empty_text"

