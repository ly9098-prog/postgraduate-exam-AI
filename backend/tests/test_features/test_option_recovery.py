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
