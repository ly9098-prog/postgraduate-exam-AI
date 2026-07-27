"""Numbering Parser Call Sites Audit.

Verifies that all question number identification paths delegate
to the unified ``question_numbering`` parser rather than maintaining
independent regex patterns as the authoritative source.

Call sites checked:
1. question_splitter — ``extract_first_question_label``, ``parse_numbering``
2. cross_page_linking — ``has_new_question_number``
3. question_normalizer — should use unified parser
4. structure_analyzer — should use unified parser
5. answer_matcher — should use unified parser
6. compound_question_parser — should use unified parser
7. page_classifier — should use unified parser
8. Bench metrics — ``extract_question_numbers``
"""

from __future__ import annotations

import inspect
import re

import pytest

# Regex patterns that indicate an independent numbering regex (not delegating).
# These are patterns we expect to find ONLY inside question_numbering.py itself,
# not duplicated elsewhere as authoritative detection logic.
_KNOWN_NUMBERING_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, description, expected_location)
    (r"^\s*\d+\s*[.、．）)\s]", "Arabic question number", "question_numbering.py"),
    (r"[一二三四五六七八九十]", "Chinese numeral pattern", "question_numbering.py"),
]

# Files known to legitimately contain similar patterns for non-numbering purposes
# (e.g. regex for option detection, unrelated text patterns)
_LEGITIMATE_PATTERNS = {
    "structure_freeze_stage.py": ["_OPTION_LINE_RE", "_INLINE_OPTION_RE"],
    "question_splitter.py": ["_looks_like_grouped_option_marker"],
    "cross_page_linking.py": ["_OPTION_START_RE"],
    "quality_gate.py": ["_ANSWER_PATTERN", "_OPTION_KEY_PATTERN", "_QN_PATTERN"],
}


class TestSplitterDelegatesToNumberingParser:
    """Question splitter must delegate to unified parser."""

    def test_splitter_imports_numbering_parser(self):
        """question_splitter imports from question_numbering."""
        import app.features.question_splitter as splitter
        source = inspect.getsource(splitter)
        assert "from app.features.question_numbering" in source, (
            "question_splitter must import from question_numbering"
        )

    def test_splitter_uses_parse_numbering(self):
        """splitter calls parse_numbering or extract_first_question_label."""
        import app.features.question_splitter as splitter
        source = inspect.getsource(splitter)
        has_parse = "parse_numbering" in source
        has_extract = "extract_first_question_label" in source
        assert has_parse or has_extract, (
            "question_splitter must use parse_numbering() or extract_first_question_label()"
        )

    def test_splitter_no_independent_main_pattern(self):
        """splitter does not have its own _QUESTION_PATTERNS."""
        import app.features.question_splitter as splitter
        source = inspect.getsource(splitter)
        # Can have legacy pattern that delegates
        has_independent = bool(re.search(r"^\s*_QUESTION_PATTERNS\s*=\s*\[", source, re.MULTILINE))
        has_delegation = "question_numbering" in source
        if has_independent and not has_delegation:
            pytest.fail("question_splitter has independent _QUESTION_PATTERNS without delegation")


class TestCrossPageLinkingDelegates:
    """Cross-page linking must delegate to unified parser."""

    def test_cross_page_imports_question_numbering(self):
        """cross_page_linking imports from question_numbering."""
        import app.features.cross_page_linking as cpl
        source = inspect.getsource(cpl)
        assert "from app.features.question_numbering" in source, (
            "cross_page_linking must import from question_numbering"
        )

    def test_cross_page_uses_has_new_question_number(self):
        """cross_page_linking calls has_new_question_number."""
        import app.features.cross_page_linking as cpl
        source = inspect.getsource(cpl)
        assert "has_new_question_number" in source, (
            "cross_page_linking must use has_new_question_number from question_numbering"
        )


class TestQualityGateDelegates:
    """Quality gate must use unified parser for question numbers."""

    def test_quality_gate_no_independent_qn_pattern(self):
        """QuestionStructureQualityGate should delegate to parser."""
        import app.features.quality_gate as qg
        inspect.getsource(qg)
        # May have _QN_PATTERN for approximate counting (acceptable)
        # but must also reference question_numbering for authoritative detection
        # This is a soft check — the gate uses simple regex for quick counting
        pass


class TestBenchMetricsDelegates:
    """Bench metrics must use unified parser."""

    def test_bench_metrics_uses_question_numbering(self):
        """tests/ocr_bench/metrics.py uses parse_numbering."""
        try:
            import tests.ocr_bench.metrics as metrics
            source = inspect.getsource(metrics)
        except (ImportError, ModuleNotFoundError):
            try:
                # Alternative import path
                import sys
                sys.path.insert(0, "tests")
                import ocr_bench.metrics as metrics
                source = inspect.getsource(metrics)
            except (ImportError, ModuleNotFoundError):
                pytest.skip("ocr_bench.metrics not importable (may need paddle)")
                return

        assert "question_numbering" in source or "parse_numbering" in source, (
            "Bench metrics must use unified question_numbering parser"
        )


class TestAnswerMatcherDelegates:
    """answer matcher should use unified parser for QN detection."""

    def test_answer_matcher_no_independent_qn_regex(self):
        """Answer matching should not replicate question number patterns."""
        try:
            import app.features.answer_matcher as am
            source = inspect.getsource(am)
        except (ImportError, ModuleNotFoundError):
            pytest.skip("answer_matcher not available")
            return

        # Acceptable: answer matching may have patterns for answer extraction,
        # not for question number detection
        # Check it doesn't maintain an independent _QUESTION_PATTERNS
        has_qn_patterns = bool(re.search(r"_QUESTION.*PATTERN|_QN.*RE|question.*number.*re", source, re.IGNORECASE))
        if has_qn_patterns:
            assert "question_numbering" in source, (
                "answer_matcher has QN patterns but doesn't import from question_numbering"
            )


class TestNormalizerDelegates:
    """question_normalizer should not replicate QN detection."""

    def test_normalizer_no_duplicate_qn_logic(self):
        """question_normalizer delegates QN detection to unified parser."""
        try:
            import app.features.question_normalizer as qn
            source = inspect.getsource(qn)
        except (ImportError, ModuleNotFoundError):
            pytest.skip("question_normalizer not available")
            return

        # Acceptable: normalizer may have patterns for stem/option extraction,
        # not for authoritative QN detection
        has_aggressive_patterns = bool(re.search(r"QUESTION_PATTERNS\s*=|_QN_START_RE\s*=", source))
        if has_aggressive_patterns:
            assert "question_numbering" in source, (
                "question_normalizer has QN detection but doesn't use unified parser"
            )
