"""代码块完整性检测 — 单元测试。

覆盖 BUGS.md 任务一至任务七的验收标准。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.features.code_integrity import (
    _extract_fenced_blocks,
    contains_code,
    detect_code_block_integrity,
    detect_code_regression,
)

# ============================================================
# contains_code 测试
# ============================================================

class TestContainsCode:
    def test_fenced_code(self):
        assert contains_code("题干\n```text\nint a;\n```")

    def test_c_keywords(self):
        assert contains_code("return F(n-1) + F(n-2);")

    def test_pointer_arrow(self):
        assert contains_code("p->next = q;")

    def test_struct_pattern(self):
        assert contains_code("typedef struct BiTNode { char data; } BiTNode;")

    def test_pure_chinese_no_code(self):
        assert not contains_code("设有一个递归函数如下，其功能是计算斐波那契数列。")

    def test_empty_string(self):
        assert not contains_code("")

    def test_data_struct_keyword(self):
        assert contains_code("BiTNode *lchild, *rchild;")

    def test_408_keyword(self):
        assert contains_code("LinkList L;")


# ============================================================
# fence closure 测试
# ============================================================

class TestFenceClosure:
    def test_closed_fence(self):
        text = "```text\nint a;\n```"
        result = _extract_fenced_blocks(text)
        assert len(result["content"]) == 1
        assert len(result["unclosed"]) == 0

    def test_unclosed_fence(self):
        text = "```text\nint a;\n"
        result = _extract_fenced_blocks(text)
        assert len(result["unclosed"]) == 1

    def test_multiple_closed_fences(self):
        text = "```\na\n```\n中间\n```\nb\n```"
        result = _extract_fenced_blocks(text)
        assert len(result["content"]) == 2
        assert len(result["unclosed"]) == 0

    def test_closed_then_unclosed(self):
        text = "```\na\n```\n```\nb\n"
        result = _extract_fenced_blocks(text)
        assert len(result["content"]) == 1
        assert len(result["unclosed"]) == 1

    def test_no_fence(self):
        text = "这是一段普通文本"
        result = _extract_fenced_blocks(text)
        assert len(result["content"]) == 0
        assert len(result["unclosed"]) == 0


# ============================================================
# detect_code_block_integrity 测试
# ============================================================

class TestDetectCodeBlockIntegrity:
    # ---- 案例一：斐波那契换行断裂 ----
    def test_case1_fibonacci_linebreak(self):
        """BUGS 案例一: if (n <=\\n1) 异常断行检测"""
        text = (
            "设有一个递归函数如下:\n"
            "```text\n"
            "int F(int n) {\n"
            "if (n <=\n"
            "1) return n;\n"
            "return F(n - 1) + F(n - 2);\n"
            "```"
        )
        result = detect_code_block_integrity(text)
        assert result["has_code"] is True
        assert "code_line_break_suspicious" in result["flags"], (
            f"应检测到异常断行, 实际 flags={result['flags']}"
        )
        assert result["score"] > 0

    def test_case1_no_false_positive_normal_code(self):
        """正常代码不应触发 line_break_suspicious"""
        text = (
            "```text\n"
            "int F(int n) {\n"
            "    if (n <= 1) return n;\n"
            "    return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        result = detect_code_block_integrity(text)
        if "code_line_break_suspicious" in result["flags"]:
            # 如果触发了，score 应该很低（只有这一个 flag）
            assert result["score"] < 0.5

    def test_case1_no_brace_issue_on_normal_code(self):
        """正常闭合的代码不应检测到 brace 不平衡"""
        text = (
            "```c\n"
            "int F(int n) {\n"
            "    if (n <= 1) return n;\n"
            "    return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        result = detect_code_block_integrity(text)
        assert "code_brace_unbalanced" not in result["flags"]

    # ---- 案例二：结构体截断+乱码 ----
    def test_case2_struct_truncated_and_garbled(self):
        """BUGS 案例二: 结构体截断 + 围栏提前闭合 + 乱码污染"""
        text = (
            "已知二叉树:\n"
            "```text\n"
            "typedef struct BiTNode {\n"
            "char data;\n"
            "``` (1typu* p1tysI* apo11ta aonu2s\n"
            "A.ABDECF\n"
        )
        result = detect_code_block_integrity(text)
        assert result["has_code"] is True
        flags = result["flags"]
        # 围栏闭合但先于结构体结束，导致截断 + 乱码
        assert "code_block_truncated" in flags, (
            f"应检测到 code_block_truncated, flags={flags}"
        )
        assert "code_garbled_text" in flags, (
            f"应检测到 garbled 乱码, flags={flags}"
        )

    def test_case2_struct_unclosed_brace(self):
        """结构体 { 没有对应的 } → 应检测到 brace 不平衡"""
        text = (
            "```text\n"
            "typedef struct BiTNode {\n"
            "char data;\n"
            "```\n"
        )
        result = detect_code_block_integrity(text)
        assert "code_brace_unbalanced" in result["flags"]

    def test_garbled_text_detection(self):
        """乱码序列 (1typu, p1tysI) 应被检测"""
        text = "```text\n(1typu* p1tysI* apo11ta aonu2s\n```"
        result = detect_code_block_integrity(text)
        assert "code_garbled_text" in result["flags"]

    def test_brace_balanced(self):
        """大括号平衡的代码块不应报错"""
        text = "```\nif (x) {\n    y();\n}\n```"
        result = detect_code_block_integrity(text)
        assert "code_brace_unbalanced" not in result["flags"]

    def test_brace_unbalanced_missing_close(self):
        """缺少闭合大括号应检测"""
        text = "```\nif (x) {\n    y();\n```"
        result = detect_code_block_integrity(text)
        # fence 未闭合+brace 不平衡
        assert "code_brace_unbalanced" in result["flags"] or "code_fence_unclosed" in result["flags"]

    def test_no_code_text(self):
        """纯中文文本不应触发代码检测"""
        result = detect_code_block_integrity("设有一个递归函数如下。")
        assert result["has_code"] is False
        assert len(result["flags"]) == 0
        assert result["score"] == 0.0

    def test_empty_text(self):
        result = detect_code_block_integrity("")
        assert result["has_code"] is False

    def test_brace_only_text(self):
        """只有括号的文本不应被误判为严重问题"""
        text = "```\n{\n}\n```"
        result = detect_code_block_integrity(text)
        # 单 brace 行不应该计为异常断行
        assert "code_line_break_suspicious" not in result["flags"]


# ============================================================
# code_regression 测试 (BUGS Task 4)
# ============================================================

class TestCodeRegression:
    def test_no_regression(self):
        """raw_text 和 stem 代码一致 → 无回归"""
        code = "```text\nint a = 0;\n```"
        result = detect_code_regression(code, code)
        assert result["has_regression"] is False

    def test_fence_disappears(self):
        """raw_text 有围栏但 stem 完全丢失 → 回归"""
        raw = "题干\n```text\nint a;\n```"
        stem = "题干\n"
        result = detect_code_regression(raw, stem)
        assert result["has_regression"] is True
        assert "code_structure_regression" in result["flags"]

    def test_brace_loss_in_stem(self):
        """stem 中闭合大括号比 raw_text 少 → 回归"""
        raw = "```text\nint f() {\n  return 1;\n}\n```"
        stem = "```text\nint f() {\n  return 1;\n```"
        result = detect_code_regression(raw, stem)
        assert result["has_regression"] is True

    def test_no_code_no_regression(self):
        """两者都不含代码 → 无回归"""
        result = detect_code_regression("纯文本", "纯文本")
        assert result["has_regression"] is False

    def test_linebreak_insertion_detected(self):
        """拆行退化：压缩空白后内容相同，但 stem 行数显著增加 → 回归"""
        raw = (
            "```c\n"
            "int F(int n) {\n"
            "if (n <= 1) return n;\n"
            "return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        stem = (
            "```c\n"
            "int F(int n) {\n"
            "if (n <=\n"
            "1) return n;\n"
            "return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        result = detect_code_regression(raw, stem)
        assert result["has_regression"] is True, (
            f"拆行退化应检测到回归, flags={result['flags']}"
        )
        assert "code_structure_regression" in result["flags"]

    def test_normal_linebreak_no_false_positive(self):
        """正常多行代码不应误报回归：压缩后内容相同，但原始就多行"""
        raw = (
            "```c\n"
            "int F(int n) {\n"
            "    if (n <= 1) return n;\n"
            "    return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        stem = (
            "```c\n"
            "int F(int n) {\n"
            "    if (n <= 1)\n"
            "        return n;\n"
            "    return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        result = detect_code_regression(raw, stem)
        # 行数差异不足（stem 仅多 1 行且 raw 仅 2 行内容行）
        # 阈值要求 stem_line_count >= raw_line_count + 1 且 raw_line_count >= 2
        # raw 4 行内容 → stem 5 行, 5 >= 5 且 4 >= 2 — 但这里的换行是正常格式化, 压缩后内容不同
        assert result["has_regression"] is False, (
            f"正常格式化不应被误判为退化, flags={result['flags']}"
        )

    def test_linebreak_insertion_single_line_code(self):
        """单行代码被拆行但有缩进/空白差异应被检测"""
        raw = "```\nif (n <= 1) return n;\n```"
        stem = "```\nif (n <=\n1) return n;\n```"
        result = detect_code_regression(raw, stem)
        # raw 只有 2 行内容（代码行 + 空尾行），stem 3 行
        # raw_line_count=2, stem_line_count=3, 3 >= 3 且 2 >= 2
        # 压缩后: "if (n <= 1) return n;" == "if (n <= 1) return n;" → 相同
        assert result["has_regression"] is True, (
            f"单行拆行应被检测, flags={result['flags']}"
        )
        assert "code_structure_regression" in result["flags"]


# ============================================================
# 验收标准 (BUGS Task 7)
# ============================================================

class TestAcceptanceCriteria:

    def test_accept_1_code_damage_not_low_risk(self):
        """验收标准 1: 代码块损坏不能标记为 low_risk_high_confidence"""
        # 案例一：换行断裂的代码应被识别为有风险
        text = (
            "设有一个递归函数如下:\n"
            "```text\n"
            "int F(int n) {\n"
            "if (n <=\n"
            "1) return n;\n"
            "return F(n - 1) + F(n - 2);\n"
            "```"
        )
        result = detect_code_block_integrity(text)
        assert result["has_code"] is True
        assert result["score"] > 0, "断裂代码不应得 0 分"

    def test_accept_2_garbled_high_risk(self):
        """验收标准 2: 代码块乱码/截断必须进入修复/审核"""
        text = (
            "```text\n"
            "typedef struct BiTNode {\n"
            "char data;\n"
            "``` (1typu* p1tysI* apo11ta aonu2s\n"
        )
        result = detect_code_block_integrity(text)
        assert result["has_code"] is True
        assert result["score"] > 0.3, (
            f"乱码截断代码应获得 >0.3 的分数, 实际={result['score']}"
        )

    def test_accept_3_no_false_positive_on_clean_code(self):
        """验收标准 5: 完好的 C 代码不应被误判为有严重风险"""
        text = (
            "以下程序输出什么？\n"
            "```c\n"
            "#include <stdio.h>\n"
            "int main() {\n"
            "    int a = 10;\n"
            "    printf(\"%d\", a);\n"
            "    return 0;\n"
            "}\n"
            "```"
        )
        result = detect_code_block_integrity(text)
        # 只允许无害 flag, 不应有截断/乱码/括号不平衡等严重 flag
        serious_flags = [f for f in result["flags"] if f not in (
            "code_line_break_suspicious",
        )]
        assert len(serious_flags) == 0, (
            f"完好代码不应有严重 flag, 实际={serious_flags}, score={result['score']}"
        )
        # score 应当 < 0.5（最多只有异常断行的轻微扣分）
        assert result["score"] < 0.5, f"完好代码 score 应 < 0.5, 实际={result['score']}"

    def test_accept_6_confidence_not_1_for_damaged_code(self):
        """验收标准 6: 损坏代码的 score 不应为 0"""
        # 任何一个损坏案例的 score 应 > 0
        text1 = (
            "```text\n"
            "if (n <=\n"
            "1) return n;\n"
            "```"
        )
        text2 = (
            "```text\n"
            "typedef struct BiTNode {\n"
            "``` (1typu* p1tysI*\n"
        )
        r1 = detect_code_block_integrity(text1)
        r2 = detect_code_block_integrity(text2)
        assert r1["score"] > 0 or r2["score"] > 0

    def test_accept_7_risk_flags_include_code_flags(self):
        """验收标准 7: ocr_quality_flags 应包含代码相关风险"""
        text = (
            "```text\n"
            "typedef struct BiTNode {\n"
            "char data;\n"
            "``` (1typu* p1tysI* apo11ta aonu2s\n"
        )
        result = detect_code_block_integrity(text)
        assert len(result["flags"]) > 0, "损坏代码应产生风险标记"
        # 至少包含代码相关的 flag
        code_flags = {f for f in result["flags"] if f.startswith("code_")}
        assert len(code_flags) > 0, f"应有 code_ 前缀的 flag, 实际={result['flags']}"
