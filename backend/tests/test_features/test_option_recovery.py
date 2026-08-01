"""Tests for deterministic OCR option recovery (option_recovery.py)."""

from __future__ import annotations

from app.features.option_recovery import (
    _render_canonical_text,
    recover_options_from_sources,
)


class TestLabeledOptionsWinOverBareCode:
    """P1 regression: bare code fragments must never overwrite real labeled options."""

    def test_short_chinese_options_survive_code_reference(self):
        primary = "A. 出栈\nB. 取顶\nC. 判空\nD. 清空"
        reference = "p = p->next\nq = q->next\nr = r->next\ns = s->next"
        result = recover_options_from_sources(primary, reference)
        assert result.options == {
            "A": "出栈",
            "B": "取顶",
            "C": "判空",
            "D": "清空",
        }
        assert result.repaired_keys == []

    def test_longer_chinese_options_survive_code_reference(self):
        primary = "A. 出栈\nB. 出栈并输出栈中元素\nC. 取栈顶元素\nD. 清空栈"
        reference = "void pop(Node* p) { p = p->next; q = q->next; }"
        result = recover_options_from_sources(primary, reference)
        assert result.options == {
            "A": "出栈",
            "B": "出栈并输出栈中元素",
            "C": "取栈顶元素",
            "D": "清空栈",
        }

    def test_code_reference_alone_fills_missing_keys(self):
        """Bare recovery fills positions with no labeled candidate; labeled
        options in the primary are never overwritten by the bare run."""
        primary = "A. 出栈\nC. 判空"
        reference = "b = b->next\nc = c->next"
        result = recover_options_from_sources(primary, reference)
        assert result.options["A"] == "出栈"
        assert result.options["C"] == "判空"
        # The bare run occupies the first two positions; B has no labeled
        # candidate, so it is filled from the run, while A keeps its label.
        assert "->" in result.options.get("B", "")


class TestRenderCanonicalTextKeepsMissingKeys:
    """P2 regression: a labeled line whose key failed recovery must be kept."""

    def test_missing_key_line_is_preserved(self):
        text = _render_canonical_text(
            "A. 甲\nB. 乙\nC. 丙",
            options={"A": "甲", "B": "乙"},
            expected=("A", "B", "C", "D"),
        )
        assert "C. 丙" in text

    def test_recovered_key_line_is_replaced(self):
        text = _render_canonical_text(
            "A. 甲\nB. 乙",
            options={"A": "甲", "B": "乙"},
            expected=("A", "B"),
        )
        assert "A. 甲" in text and "B. 乙" in text


class TestMirrorRepair:
    def test_mirror_signature_repaired(self):
        # "xau<-s" is the mirrored form of "s->xau" produced by OCR.
        primary = "A. 甲\nB. 乙\nC. 丙\nD. 丁"
        reference = "if (xau<-s) return;"
        result = recover_options_from_sources(primary, reference)
        assert result.options["A"] == "甲"
        assert result.options["B"] == "乙"


class TestKnownGroupFuzzyRecovery:
    """023-family: OCR-degraded known-group fragments fill missing keys."""

    def test_suffix_and_homophone_fragments_recover_c_d(self):
        text = "所有节点\n连表\nA. 找到头结点\nB. 找到尾结点"
        result = recover_options_from_sources(text)
        assert result.options["C"] == "删除所有节点"
        assert result.options["D"] == "逆置链表"
        assert set(result.options) == {"A", "B", "C", "D"}

    def test_real_023_vl_shape(self):
        text = (
            "C\n"
            "    LNode *p = L;\n"
            "    while (p != NULL && p->next != NULL) {\n"
            "        p = p->next;\n"
            "    }\n"
            "    该代码的作用是：\n"
            "    所有节点\n"
            "    连表\n"
            "A. 找到头结点\n"
            "B. 找到尾结点"
        )
        result = recover_options_from_sources(text)
        assert result.options["C"] == "删除所有节点"
        assert result.options["D"] == "逆置链表"

    def test_recovery_is_audited_in_warnings(self):
        text = "所有节点\n连表\nA. 找到头结点\nB. 找到尾结点"
        result = recover_options_from_sources(text)
        assert "known_group_fragment_recovered:C,D" in result.warnings

    def test_consumed_fragments_dropped_from_rendered_text(self):
        text = "所有节点\n连表\nA. 找到头结点\nB. 找到尾结点"
        result = recover_options_from_sources(text)
        lines = [ln.strip() for ln in result.text.splitlines()]
        assert "所有节点" not in lines
        assert "连表" not in lines
        assert "C. 删除所有节点" in lines
        assert "D. 逆置链表" in lines

    def test_lone_fragment_without_anchor_does_not_synthesize_group(self):
        # A/B are not this group's literals, so there is no full-member anchor.
        text = "所有节点\nA. 与已知组选项无关\nB. 其他答案"
        result = recover_options_from_sources(text)
        assert "C" not in result.options
        assert "D" not in result.options

    def test_missing_c_d_without_source_fragments_not_filled(self):
        text = "A. 找到头结点\nB. 找到尾结点\n无关文本"
        result = recover_options_from_sources(text)
        assert set(result.options) == {"A", "B"}


class TestLeadingBareOptionRecovery:
    """025-family: a single bare code line before B is recovered as A."""

    def test_bare_code_line_before_b_recovers_a(self):
        text = (
            "' d->next = s->next; s->next = d\n"
            "B. s->next = p->next; p->next = s\n"
            "C. p->next = s; s = p->next\n"
            "D. s = p; p->next = NULL"
        )
        result = recover_options_from_sources(text)
        assert result.options["A"] == "d->next = s->next; s->next = d"
        assert set(result.options) == {"A", "B", "C", "D"}
        # The consumed bare line is dropped so it is not duplicated beside A.
        assert "d->next = s->next; s->next = d\nA." not in result.text
        assert "A. d->next = s->next; s->next = d" in result.text

    def test_mirror_input_normalized_then_a_recovered(self):
        text = (
            "d = xau<-s :xau<-s = jxau<-d\n"
            "B. s->next = p->next; p->next = s\n"
            "C. p->next = s; s = p->next\n"
            "D. s = p; p->next = NULL"
        )
        result = recover_options_from_sources(text)
        assert result.options["A"] == "d->next = s->next; s->next = d"
        assert result.mirror_repairs > 0

    def test_a_not_recovered_when_b_missing_but_a_present(self):
        # A is present; the rule only ever fills A, so the bare line must not
        # be mislabelled as the missing B.
        text = (
            "d->next = s->next; s->next = d\n"
            "A. 甲\n"
            "C. 丙\n"
            "D. 丁"
        )
        result = recover_options_from_sources(text)
        assert "B" not in result.options

    def test_chinese_prose_before_b_not_recovered(self):
        text = "这是题干说明\nB. 甲\nC. 乙\nD. 丙"
        result = recover_options_from_sources(text)
        assert "A" not in result.options

    def test_bare_line_too_far_not_recovered(self):
        text = (
            "typedef struct LNode {\n"
            "int data;\n"
            "} LNode;\n"
            "已知 p 指向某节点：\n"
            "B. 甲\n"
            "C. 乙\n"
            "D. 丙"
        )
        result = recover_options_from_sources(text)
        assert "A" not in result.options

    def test_disordered_labels_block_bare_recovery(self):
        text = (
            "d->next = s->next; s->next = d\n"
            "B. 甲\n"
            "D. 丁\n"
            "C. 丙"
        )
        result = recover_options_from_sources(text)
        assert "A" not in result.options

    def test_code_block_header_not_swallowed(self):
        text = (
            "LNode *p = L;\n"
            "while (p != NULL) {\n"
            "    p = p->next;\n"
            "}\n"
            "该代码的作用是：\n"
            "A. 找到头结点"
        )
        result = recover_options_from_sources(text)
        assert "B" not in result.options
        assert result.options["A"] == "找到头结点"

    def test_complete_block_untouched(self):
        text = "A. 甲\nB. 乙\nC. 丙\nD. 丁"
        result = recover_options_from_sources(text)
        assert result.options == {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
        assert result.repaired_keys == []
