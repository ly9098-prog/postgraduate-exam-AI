"""Tests for the Structure Freeze Layer.

Tests cover:
1. Option detection completeness (all four patterns)
2. Option immutability through normalize_schema
3. AI repair preserving frozen options
4. Deterministic output for identical input
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.features.pipeline_stages.structure_freeze_stage import (
    _compute_confidence,
    _detect_inline_options,
    _detect_option_line,
    run_structure_freeze_stage,
)
from app.features.question_normalizer import normalize_output, normalize_question

# =========================================================================
# Helpers
# =========================================================================


def _make_block(text: str, page: int = 1, block_index: int = 0) -> dict:
    return {"page": page, "block_index": block_index, "normalized_text": text}


def _make_raw_question(
    raw_text: str,
    option_lines: dict[str, str] | None = None,
    is_frozen: bool = False,
    number: int = 1,
    page: int = 1,
) -> dict:
    """Build a minimal raw_question dict for testing."""
    q: dict = {
        "number": number,
        "raw_question_text": raw_text,
        "page_start": page,
        "page_end": page,
        "has_options": bool(option_lines),
        "option_lines": option_lines or {},
        "confidence": 0.9,
    }
    if is_frozen:
        q["is_frozen"] = True
    return q


# =========================================================================
# 1. Options not lost — freeze output must be complete
# =========================================================================


class TestOptionsNotLost:
    """OCR input with A/B/C/D — freeze output must be complete."""

    def test_separate_lines_abcd(self):
        """Each option on its own line: A. B. C. D."""
        blocks = [
            _make_block("1. 题目内容", page=1, block_index=0),
            _make_block("A. 选项一的内容", page=1, block_index=1),
            _make_block("B. 选项二的内容", page=1, block_index=2),
            _make_block("C. 选项三的内容", page=1, block_index=3),
            _make_block("D. 选项四的内容", page=1, block_index=4),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        # Each option block should have at least its own key
        assert any("A" in v for v in registry.values()), "Option A not detected"
        assert any("B" in v for v in registry.values()), "Option B not detected"
        assert any("C" in v for v in registry.values()), "Option C not detected"
        assert any("D" in v for v in registry.values()), "Option D not detected"
        assert len(result["frozen_structures"]) >= 4, "Expected at least 4 frozen structures"

    def test_inline_options(self):
        """All options on one line: A.xxx B.xxx C.xxx D.xxx."""
        blocks = [
            _make_block("1. 题目内容", page=1, block_index=0),
            _make_block("A. 甲 B. 乙 C. 丙 D. 丁", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert combined.get("A") == "甲"
        assert combined.get("B") == "乙"
        assert combined.get("C") == "丙"
        assert combined.get("D") == "丁"

    def test_circled_options(self):
        """Circled digit options: ①. ②. ③. ④."""
        blocks = [
            _make_block("1. 题目内容", page=1, block_index=0),
            _make_block("①. 甲 ②. 乙 ③. 丙 ④. 丁", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert "A" in combined, "① should map to A"
        assert "B" in combined, "② should map to B"
        assert "C" in combined, "③ should map to C"
        assert "D" in combined, "④ should map to D"

    def test_paren_options(self):
        """Parenthesized options: (A) (B) (C) (D)."""
        blocks = [
            _make_block("1. 题目内容", page=1, block_index=0),
            _make_block("(A) 第一 (B) 第二 (C) 第三 (D) 第四", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert "A" in combined
        assert "B" in combined
        assert "C" in combined
        assert "D" in combined

    def test_option_lines_detected_across_separate_blocks(self):
        """Each option on its own block — both must be detected."""
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("A. 这是第一行", page=1, block_index=1),
            _make_block("B. 这是第二行", page=1, block_index=2),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        assert any("A" in v for v in registry.values())
        assert any("B" in v for v in registry.values())

    def test_continuation_line_not_detected_as_option(self):
        """Non-option continuation text after an option line is NOT merged.

        The freeze stage detects option markers but does NOT assemble
        multi-line option text — continuation text that wraps to the next
        line without an option marker is skipped. This is by design:
        the downstream splitter is responsible for merging continuation
        lines into the preceding option.
        """
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("A. 这是第一行的开头部分\n续表内容", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        # The "A" option text only captures the line with the marker
        for v in registry.values():
            assert "A" in v, "A should be detected"
            # Continuation text is NOT merged into the option at freeze stage
            assert "续表内容" not in v.get("A", ""), (
                "Continuation line should not be merged at freeze stage"
            )

    def test_lowercase_options(self):
        """Lowercase a. b. c. d. patterns must be detected as A B C D."""
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("a. 甲 b. 乙 c. 丙 d. 丁", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert combined.get("A") == "甲"
        assert combined.get("B") == "乙"
        assert combined.get("C") == "丙"
        assert combined.get("D") == "丁"

    def test_chinese_punctuation_separator(self):
        """Options with Chinese enumeration comma A、B、C、D."""
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("A、甲 B、乙 C、丙 D、丁", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert combined.get("A") == "甲"
        assert combined.get("B") == "乙"
        assert combined.get("C") == "丙"
        assert combined.get("D") == "丁"

    def test_latex_in_option_text(self):
        """Option text containing LaTeX must not break detection.

        Note: \frac (contains 'a') is excluded from inline detection because
        the inline regex uses [^A-Da-d\n] as a stop-character set. This is
        a known limitation — multi-line per-option detection handles it.
        """
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("A. $f(x)=x^2$ B. $\\int$ C. $\\sum$ D. $\\pi$", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert "$f(x)=x^2$" in combined.get("A", "")
        assert "$\\int$" in combined.get("B", "")
        assert "$\\sum$" in combined.get("C", "")
        assert "$\\pi$" in combined.get("D", "")

    def test_bare_option_marker_no_text_skipped(self):
        """A marker with no option text (e.g. 'A.  ' alone) must be skipped."""
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("A.  ", page=1, block_index=1),
            _make_block("B. 实际的选项", page=1, block_index=2),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        # "A.   " should not produce an option entry
        # Only B should be detected
        b_found = any(k == "B" for v in registry.values() for k in v)
        a_found = any(k == "A" for v in registry.values() for k in v)
        assert b_found, "B should be detected"
        assert not a_found, "Bare A without text should be skipped"

    def test_option_with_parenthesized_answers(self):
        """Options followed by answer annotations in parens: A. 甲（对）B. 乙（错）."""
        blocks = [
            _make_block("1. 题目", page=1, block_index=0),
            _make_block("A. 甲（对）B. 乙（错）C. 丙（对）D. 丁（错）", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        registry = result["frozen_option_registry"]
        combined: dict = {}
        for v in registry.values():
            combined.update(v)
        assert combined.get("A") == "甲（对）"
        assert combined.get("B") == "乙（错）"

    def test_empty_blocks_returns_empty(self):
        """Empty input should return empty result."""
        result = run_structure_freeze_stage([])
        assert result["frozen_option_registry"] == {}
        assert result["frozen_structures"] == []
        assert "empty_blocks" in result["warnings"]

    def test_no_options_detected_warns(self):
        """Text with no option patterns should produce warning."""
        blocks = [
            _make_block("这是一段普通的文本，不包含任何选项", page=1, block_index=0),
        ]
        result = run_structure_freeze_stage(blocks)
        assert result["frozen_option_registry"] == {}
        assert "no_options_detected" in result["warnings"]


# =========================================================================
# 2. Options not modified by normalize_schema
# =========================================================================


class TestOptionsNotModified:
    """Once frozen, options must survive normalize_schema unchanged."""

    def test_frozen_options_preserved_through_normalize(self):
        """Frozen option_lines should be preserved through normalize_question."""
        raw_text = "1. 测试题干\nA. 选项甲\nB. 选项乙\nC. 选项丙\nD. 选项丁"
        option_lines = {"A": "选项甲", "B": "选项乙", "C": "选项丙", "D": "选项丁"}

        raw_q = _make_raw_question(raw_text, option_lines, is_frozen=True)
        matched = {"question_number": 1, "answer": "A", "explanation": ""}
        result = normalize_question(raw_q, matched)

        assert result.get("is_frozen"), "is_frozen flag should be preserved"
        opts = result.get("options", [])
        opt_keys = sorted(o.get("key", "") for o in opts)
        assert opt_keys == ["A", "B", "C", "D"], f"Expected A-D keys, got {opt_keys}"

    def test_frozen_options_not_cleared_by_quality_gate(self):
        """Frozen options must survive even when quality gate flags corruption."""
        raw_text = "1. 题干\nA. 选项甲\nB. 选项乙\nC. 选项丙\nD. 选项丁"
        option_lines = {"A": "选项甲", "B": "选项乙", "C": "选项丙", "D": "选项丁"}

        raw_q = _make_raw_question(raw_text, option_lines, is_frozen=True)
        matched = {"question_number": 1, "answer": "A", "explanation": ""}
        result = normalize_question(raw_q, matched)

        # Even if quality gate might downgrade confidence, options must survive
        opts = result.get("options", [])
        assert len(opts) == 4, f"Expected 4 options, got {len(opts)}"

    def test_frozen_options_no_padding_in_normalize_output(self):
        """normalize_output should not pad frozen options."""
        question = {
            "stem": "test stem",
            "options": [{"key": "A", "text": "只有A"}],
            "question_type": "single_choice",
            "is_frozen": True,
            "answer": "A",
            "analysis": "",
        }
        result = normalize_output(question)
        opts = result.get("options", [])
        keys = sorted(o.get("key", "") for o in opts)
        # Frozen: exactly what was there, no padding
        assert keys == ["A"], f"Frozen options should not be padded, got {keys}"
        assert len(opts) == 1, f"Expected 1 frozen option, got {len(opts)}"

    def test_non_frozen_no_padding(self):
        """Non-frozen single_choice: no padding — options preserved as-is."""
        question = {
            "stem": "test stem",
            "options": [{"key": "A", "text": "只有A"}],
            "question_type": "single_choice",
            "answer": "A",
            "analysis": "",
        }
        result = normalize_output(question)
        opts = result.get("options", [])
        keys = sorted(o.get("key", "") for o in opts)
        assert keys == ["A"], f"Non-frozen should NOT pad, got {keys}"


# =========================================================================
# 3. AI repair preserves frozen options
# =========================================================================


class TestAIRepairPreservesOptions:
    """AI repair must not modify frozen options."""

    def _make_frozen_question(self) -> dict:
        """Create a frozen question that will trigger AI repair (low confidence)."""
        return {
            "schema_version": "v1",
            "subject": "math2",
            "question_type": "single_choice",
            "stem": "",
            "options": [{"key": "A", "text": "OriginalA"}, {"key": "B", "text": "OriginalB"}],
            "answer": "",
            "analysis": "",
            "raw_text": "1. 测试题\nA. OriginalA\nB. OriginalB",
            "knowledge_points": [],
            "difficulty": 3,
            "source": {"file": "test.pdf", "page": 1, "type": "pdf"},
            "is_valid": False,
            "is_frozen": True,
            "errors": ["missing_stem", "missing_answer"],
            "warnings": [],
            "stem_hash": "abc12345",
            "confidence_score": 0.15,
        }

    def _modified_options_ai_response(self) -> dict:
        """AI response that attempts to modify frozen options."""
        return {
            "question_type": "single_choice",
            "stem": "测试题题干",
            "options": {"A": "ModifiedA", "B": "ModifiedB"},
            "answer": "A",
            "analysis": "",
            "confidence": 0.9,
            "repair_actions": ["stem_cleaned"],
        }

    def test_ai_repair_frozen_guard_rejects_modification(self):
        """Call real repair_questions with mocked AI; verify frozen guard works."""
        from app.features.ai_repair import repair_questions
        from app.features.token_budget import _token_usage

        # Reset token budget (other tests may have exhausted it)
        _token_usage["daily"] = 0
        _token_usage["monthly"] = 0

        q = self._make_frozen_question()
        mock_response = {
            "content": json.dumps(self._modified_options_ai_response()),
            "tokens_used": 350,
            "model": "deepseek-chat",
            "duration_ms": 800,
        }
        mocks = {
            "is_available": MagicMock(return_value=True),
            "chat": AsyncMock(return_value=mock_response),
        }
        with patch("app.ai.client.deepseek.is_available", mocks["is_available"]), \
             patch("app.ai.client.deepseek.chat", mocks["chat"]):
            result = asyncio.run(repair_questions([q]))

        # Frozen guard should reject the AI's option modification →
        # question goes to unrepaired, not repaired
        assert result["stats"]["repaired"] == 0, (
            "AI should NOT be allowed to modify frozen options"
        )
        assert result["stats"]["unrepaired"] >= 1
        unreported_reasons = [u["reason"] for u in result["unrepaired"]]
        assert "options_modified_by_ai" in unreported_reasons, (
            f"Expected options_modified_by_ai, got {unreported_reasons}"
        )

    def test_repair_stage_prompt_constraint(self):
        """The repair prompt must include options freeze constraint."""
        from app.ai.prompts import SYSTEM_PROMPTS

        prompt = SYSTEM_PROMPTS["question_repair"]
        assert "禁止修改 options" in prompt, (
            "Repair prompt should forbid option modification"
        )


# =========================================================================
# 4. Deterministic test
# =========================================================================


class TestDeterministic:
    """Same OCR input must produce identical frozen structure."""

    def test_identical_input_identical_output(self):
        """Running freeze stage twice on same blocks yields same result."""
        blocks = [
            _make_block("1. 题干", page=1, block_index=0),
            _make_block("A. 甲", page=1, block_index=1),
            _make_block("B. 乙", page=1, block_index=2),
            _make_block("C. 丙", page=1, block_index=3),
            _make_block("D. 丁", page=1, block_index=4),
        ]

        result1 = run_structure_freeze_stage(blocks)
        result2 = run_structure_freeze_stage(blocks)

        assert result1["frozen_option_registry"] == result2["frozen_option_registry"]
        assert result1["frozen_structures"] == result2["frozen_structures"]

    def test_no_randomness_in_detection(self):
        """Detection functions are pure and deterministic."""
        line = "A. 测试选项"
        r1 = _detect_option_line(line)
        r2 = _detect_option_line(line)
        assert r1 == r2

        text = "A. 甲 B. 乙 C. 丙"
        o1 = _detect_inline_options(text)
        o2 = _detect_inline_options(text)
        assert o1 == o2

        opts = {"A": "a", "B": "b"}
        c1 = _compute_confidence(opts)
        c2 = _compute_confidence(opts)
        assert c1 == c2

    def test_different_blocks_order_different_keys(self):
        """Different blocks produce different registry keys."""
        blocks_a = [_make_block("A. 选项", page=1, block_index=1)]
        blocks_b = [_make_block("A. 选项", page=2, block_index=1)]

        r1 = run_structure_freeze_stage(blocks_a)
        r2 = run_structure_freeze_stage(blocks_b)

        # Different page → different registry key
        assert list(r1["frozen_option_registry"].keys()) != list(r2["frozen_option_registry"].keys())

    def test_confidence_computation(self):
        """Confidence reflects option completeness."""
        assert _compute_confidence({"A": "a", "B": "b", "C": "c", "D": "d"}) == 1.0
        assert _compute_confidence({"A": "a", "B": "b", "C": "c"}) == 0.7
        assert _compute_confidence({"A": "a", "B": "b"}) == 0.5
        assert _compute_confidence({"A": "a"}) == 0.3
        assert _compute_confidence({}) == 0.3


# =========================================================================
# 5. Integration with pipeline
# =========================================================================


class TestPipelineIntegration:
    """End-to-end integration tests for the freeze stage."""

    def test_freeze_applies_to_raw_questions(self):
        """_apply_frozen_options enriches raw_questions with frozen data."""
        from app.features.pipeline_orchestrator import _apply_frozen_options

        raw_questions = [
            {
                "number": 1,
                "raw_question_text": "题干\nA. 选项甲\nB. 选项乙",
                "option_lines": {},
                "has_options": False,
            }
        ]
        frozen_registry = {
            "1:1": {"A": "选项甲", "B": "选项乙"},
        }
        normalized_blocks = [
            {"page": 1, "block_index": 1, "normalized_text": "A. 选项甲\nB. 选项乙"}
        ]

        _apply_frozen_options(
            raw_questions, frozen_registry,
            normalized_blocks=normalized_blocks,
        )
        q = raw_questions[0]
        assert q.get("is_frozen"), "Question should be marked frozen"
        assert q.get("has_options"), "Question should have options"
        assert "A" in q.get("option_lines", {}), "Option A should be present"

    def test_freeze_stage_output_shape(self):
        """Freeze stage output has expected keys."""
        blocks = [
            _make_block("1. 题干", page=1, block_index=0),
            _make_block("A. 甲", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)

        assert "frozen_option_registry" in result
        assert "frozen_structures" in result
        assert "warnings" in result
        assert "freeze_checksum" in result
        # frozen_option_registry is wrapped in MappingProxyType for immutability
        assert isinstance(result["frozen_option_registry"], dict) or hasattr(result["frozen_option_registry"], "keys")
        assert isinstance(result["frozen_structures"], list)
        assert isinstance(result["warnings"], list)
        assert isinstance(result["freeze_checksum"], str) and len(result["freeze_checksum"]) > 0

    def test_frozen_structure_has_required_fields(self):
        """Each frozen structure dict has required fields."""
        blocks = [
            _make_block("1. 题干", page=1, block_index=0),
            _make_block("A. 甲", page=1, block_index=1),
        ]
        result = run_structure_freeze_stage(blocks)
        for s in result["frozen_structures"]:
            assert "page" in s
            assert "block_index" in s
            assert "options" in s
            assert "option_keys" in s
            assert "is_frozen" in s and s["is_frozen"]
            assert "is_complete" in s
            assert "confidence" in s
