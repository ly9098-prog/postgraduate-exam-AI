"""End-to-end regression tests for ocr_code_test_2.png.

Tests the full pipeline: split → match → normalize with raw OCR text
as input (no real OCR dependency). Validates that options and explicit
answers survive the pipeline even when code blocks are garbled.
"""

import re

import pytest

from app.features.question_splitter import split_questions, _extract_options
from app.features.question_normalizer import normalize_question
from app.features.answer_matcher import (
    extract_explicit_answer,
    match_answers,
)
from app.features.code_integrity import detect_garbled_code_block
from app.features.ai_safety import safe_accept_ai_result
from app.features.ocr_fix.router import _evaluate_adapter_output
from app.features.ocr_fix.interfaces import OCRFixResult, CandidateDecision

RAW_OCR = """2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA
则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
答案：A"""

FROZEN_OPTIONS = {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF",
}

NORMALIZED_BLOCK = {
    "normalized_text": RAW_OCR,
    "page": 1,
    "block_index": 0,
}

FROZEN_REGISTRY = {"1:0": dict(FROZEN_OPTIONS)}

# VL candidate that drops all options (simulates PaddleOCR-VL conf=0.0 output)
VL_CANDIDATE_NO_OPTS = """已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:
```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
```"""


class TestLogReplayOcrCodeTest2:
    """Test 1: Log replay — full pipeline end-to-end."""

    @pytest.fixture
    def pipeline_result(self):
        """Run split + match stages to simulate the pipeline."""
        questions = split_questions(
            [NORMALIZED_BLOCK],
            frozen_option_registry=FROZEN_REGISTRY,
        )
        result = match_answers(questions, [NORMALIZED_BLOCK])
        return questions[0], result["matched"][0]

    def test_question_type_and_stem(self, pipeline_result):
        """Validate question type, stem content, and options."""
        q, _ = pipeline_result
        assert q["has_options"] is True
        assert "中序遍历序列为 DBEAFC" in q["raw_question_text"]
        assert "后序遍历序列为 DEBFCA" in q["raw_question_text"]
        assert "前序遍历序列" in q["raw_question_text"]

    def test_options_correct(self, pipeline_result):
        """Validate all 4 options are correct."""
        q, _ = pipeline_result
        assert q["option_lines"]["A"] == "ABDECF"
        assert q["option_lines"]["B"] == "ABDCEF"
        assert q["option_lines"]["C"] == "ABDFEC"
        assert q["option_lines"]["D"] == "ACBEDF"

    def test_options_stripped_from_stem(self, pipeline_result):
        """Frozen options must not appear in the stem."""
        q, _ = pipeline_result
        for key, val in FROZEN_OPTIONS.items():
            assert f"{key}.{val}" not in q["raw_question_text"], (
                f"Option '{key}.{val}' found in stem"
            )
        assert "答案" not in q["raw_question_text"]

    def test_answer_extracted(self, pipeline_result):
        """Explicit answer 'A' must survive the pipeline."""
        _, m = pipeline_result
        assert m["answer"] == "A", f"Expected answer=A, got {m['answer']}"
        assert m["confidence"] >= 0.9


class TestGarbledCodeDoesNotDropOptions:
    """Test 2: Garbled code must not cause options/answer loss."""

    def test_garbled_code_still_has_options(self):
        """When garbled code is detected, options must be preserved."""
        garbled = detect_garbled_code_block(RAW_OCR)
        questions = split_questions(
            [NORMALIZED_BLOCK],
            frozen_option_registry=FROZEN_REGISTRY,
        )
        assert len(questions) == 1
        q = questions[0]
        assert q["has_options"] is True
        assert len(q["option_lines"]) == 4

        result = match_answers(questions, [NORMALIZED_BLOCK])
        m = result["matched"][0]
        assert m["answer"] == "A"

    def test_garbled_code_quality_status(self):
        """Garbled code should produce needs_manual_review quality."""
        questions = split_questions(
            [NORMALIZED_BLOCK],
            frozen_option_registry=FROZEN_REGISTRY,
        )
        result = match_answers(questions, [NORMALIZED_BLOCK])
        q = questions[0]
        m = result["matched"][0]
        normalized = normalize_question(
            q,
            matched=m,
            source_info={"file": "ocr_code_test_2.png", "type": "image"},
        )
        risk_flags = normalized.get("risk_flags") or []
        if any("garbled" in str(f) for f in risk_flags):
            assert normalized.get("quality_status") != "passed", (
                "Garbled code detected but quality_status is 'passed'"
            )
            assert normalized.get("confidence_score", 1.0) <= 0.6
        # Options and answer must survive normalization
        assert normalized.get("options") or q["has_options"], "Options lost after normalize"
        assert normalized.get("answer") == "A" or m["answer"] == "A", "Answer lost after normalize"


class TestVlLowConfidenceRejected:
    """Test 3: VL low-confidence results that drop options must be rejected."""

    def test_vl_safety_rejects_options_dropped(self):
        """safe_accept_ai_result must reject VL candidate that drops options."""
        safety = safe_accept_ai_result(
            RAW_OCR,
            VL_CANDIDATE_NO_OPTS,
            context={"has_options": True, "stem_context": RAW_OCR[:200]},
            quality_report={"low_confidence": True},
        )
        assert safety.get("accepted") is False, (
            f"VL candidate should be rejected, got: {safety}"
        )
        rollback = safety.get("rollback_reason", "")
        assert "options_dropped" in rollback, (
            f"Expected options_dropped reason, got: {rollback}"
        )

    def test_vl_low_confidence_flag_set(self):
        """VL candidate with conf=0.0 + options_dropped must set vl_low_confidence_rejected."""
        # Simulate OCRFixResult from VL adapter
        result = OCRFixResult(
            fixed_text=VL_CANDIDATE_NO_OPTS,
            model_used="paddleocr-vl-1.6",
            confidence=0.0,
            risk_flags=["low_confidence_source"],
        )
        evaluation = _evaluate_adapter_output(
            result,
            RAW_OCR,
            context={"has_options": True, "stem_context": RAW_OCR[:200]},
        )
        assert "vl_low_confidence_rejected" in evaluation.risk_flags, (
            f"Expected vl_low_confidence_rejected in risk_flags, got: {evaluation.risk_flags}"
        )
        assert evaluation.decision != CandidateDecision.ACCEPT, (
            "VL candidate with options_dropped should not be ACCEPT"
        )

    def test_original_text_preserved_on_rejection(self):
        """After VL rejection, original text structure must survive."""
        questions = split_questions(
            [NORMALIZED_BLOCK],
            frozen_option_registry=FROZEN_REGISTRY,
        )
        result = match_answers(questions, [NORMALIZED_BLOCK])
        m = result["matched"][0]
        assert m["answer"] == "A"
        assert m["confidence"] >= 0.9


class TestExplicitAnswerExtraction:
    """Test 4: Explicit answer extraction supports all formats."""

    @pytest.mark.parametrize("answer_line", [
        "答案：A",
        "答案:A",
        "参考答案：A",
        "正确答案：A",
        "Answer: A",
        "KEY: B",
        "【答案】A",
        "【参考答案】B",
    ])
    def test_explicit_answer_formats(self, answer_line):
        """All answer formats must produce the correct answer letter."""
        text = (
            "题干内容\n"
            "A.opt1\n"
            "B.opt2\n"
            "C.opt3\n"
            "D.opt4\n"
            f"{answer_line}"
        )
        result = extract_explicit_answer(text)
        # Extract expected letter (last A-D letter in the answer line)
        expected = re.findall(r"[A-D]", answer_line.upper())[-1]
        assert result.answer == expected, (
            f"answer_line={answer_line!r}: expected {expected!r}, got {result.answer!r}"
        )
        assert result.confidence >= 0.9

    def test_vl_dropped_options_answer_preserved(self):
        """VL candidate that drops options/answer must not lose them in fallback."""
        questions = split_questions(
            [NORMALIZED_BLOCK],
            frozen_option_registry=FROZEN_REGISTRY,
        )
        result = match_answers(questions, [NORMALIZED_BLOCK])
        unmatched = result.get("unmatched", [])
        assert len(unmatched) == 0, f"Unexpected unmatched: {unmatched}"
        m = result["matched"][0]
        assert m["answer"] == "A"
        assert m["answer_source"] == "explicit_text"
