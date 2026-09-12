"""Tests for app.evaluation.split_quality."""

from __future__ import annotations

from app.evaluation.split_quality import evaluate_split_quality


def _make_question(number: int, has_options: bool = True, confidence: float = 0.9):
    return {
        "number": number,
        "has_options": has_options,
        "confidence": confidence,
        "option_lines": {"A": "opt1", "B": "opt2"} if has_options else {},
        "raw_question_text": f"Question {number} text",
    }


class TestEvaluateSplitQuality:
    def test_empty_questions(self):
        result = evaluate_split_quality([])
        assert result["split_quality_score"] == 0.0
        assert result["option_recovery_rate"] == 0.0
        assert result["order_accuracy"] == 1.0
        assert result["question_count"] == 0
        assert "warnings" in result

    def test_single_question(self):
        qs = [_make_question(1)]
        result = evaluate_split_quality(qs)
        assert result["split_quality_score"] > 0
        assert result["option_recovery_rate"] == 1.0
        assert result["order_accuracy"] == 1.0
        assert result["question_count"] == 1

    def test_sequential_questions(self):
        qs = [_make_question(i) for i in range(1, 6)]
        result = evaluate_split_quality(qs)
        assert result["order_accuracy"] == 1.0
        assert result["option_recovery_rate"] == 1.0

    def test_non_sequential_questions(self):
        qs = [_make_question(i) for i in [1, 2, 3, 5, 6]]
        result = evaluate_split_quality(qs)
        assert result["order_accuracy"] < 1.0

    def test_partial_option_recovery(self):
        qs = [
            _make_question(1, has_options=True),
            _make_question(2, has_options=False),
            _make_question(3, has_options=False),
            _make_question(4, has_options=True),
        ]
        result = evaluate_split_quality(qs)
        assert result["option_recovery_rate"] == 0.5
        assert result["with_options_count"] == 2

    def test_no_options(self):
        qs = [
            _make_question(1, has_options=False),
            _make_question(2, has_options=False),
        ]
        result = evaluate_split_quality(qs)
        assert result["option_recovery_rate"] == 0.0
        assert "warnings" in result

    def test_confidence_distribution(self):
        qs = [
            _make_question(1, confidence=0.9),
            _make_question(2, confidence=0.6),
            _make_question(3, confidence=0.3),
        ]
        result = evaluate_split_quality(qs)
        dist = result["confidence_distribution"]
        assert dist["high"]["count"] == 1
        assert dist["medium"]["count"] == 1
        assert dist["low"]["count"] == 1

    def test_all_high_confidence(self):
        qs = [_make_question(i, confidence=0.95) for i in range(1, 4)]
        result = evaluate_split_quality(qs)
        assert result["avg_confidence"] == 0.95
        assert result["confidence_distribution"]["high"]["count"] == 3

    def test_split_mode_from_diagnostics(self):
        qs = [_make_question(1)]
        diag = {"split_mode": "layout_enhanced"}
        result = evaluate_split_quality(qs, split_diagnostics=diag)
        assert result["split_mode"] == "layout_enhanced"

    def test_scoring_weights(self):
        # Full score scenario
        qs = [_make_question(i, has_options=True, confidence=1.0) for i in range(1, 4)]
        result = evaluate_split_quality(qs)
        # expected: 1.0*0.4 + 1.0*0.3 + 1.0*0.3 = 1.0
        assert result["split_quality_score"] == 1.0

        # No options, but high confidence and good order
        qs2 = [_make_question(i, has_options=False, confidence=1.0) for i in range(1, 4)]
        result2 = evaluate_split_quality(qs2)
        # 0.0*0.4 + 1.0*0.3 + 1.0*0.3 = 0.6
        assert result2["split_quality_score"] == 0.6

    def test_warnings_on_low_option_recovery(self):
        qs = [_make_question(i, has_options=False) for i in range(1, 4)]
        result = evaluate_split_quality(qs)
        warnings = result.get("warnings", [])
        assert any("option recovery" in w for w in warnings)

    def test_warnings_on_order_issue(self):
        qs = [_make_question(i) for i in [1, 3, 5]]  # gap, but sequential from 1
        # numbers are [1, 3, 5], expected = [1, 2, 3], so 2/3 wrong
        result = evaluate_split_quality(qs)
        warnings = result.get("warnings", [])
        # order_accuracy should be 1/3 = 0.333, which is < 0.8
        assert any("order" in w for w in warnings)
