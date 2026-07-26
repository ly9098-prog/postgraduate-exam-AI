"""Tests for batch_validation module."""

from app.features.batch_validation import (
    _check_answer_presence,
    _check_number_continuity,
    _check_option_completeness,
    validate_batch_structure,
)


class TestNumberContinuity:
    def _make_questions(self, raw_texts):
        return [{"raw_text": t, "question_type": "single_choice", "options": [], "answer": ""} for t in raw_texts]

    def test_sequential_no_gaps(self):
        questions = self._make_questions(["1. 题目A", "2. 题目B", "3. 题目C"])
        gaps = _check_number_continuity(questions)
        assert gaps == []

    def test_gap_detected(self):
        questions = self._make_questions(["1. 题目A", "2. 题目B", "5. 题目E"])
        gaps = _check_number_continuity(questions)
        assert len(gaps) == 2
        assert gaps[0]["expected"] == 3
        assert gaps[1]["expected"] == 4

    def test_section_reset_not_flagged(self):
        questions = self._make_questions(["1. 题A", "2. 题B", "3. 题C", "1. 新节题A", "2. 新节题B"])
        gaps = _check_number_continuity(questions)
        assert gaps == []


class TestOptionCompleteness:
    def test_full_options_pass(self):
        q = {
            "question_type": "single_choice",
            "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}, {"key": "C", "text": "z"}, {"key": "D", "text": "w"}],
        }
        assert _check_option_completeness(q, 0) is None

    def test_missing_c_flagged(self):
        q = {
            "question_type": "single_choice",
            "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}, {"key": "D", "text": "w"}],
        }
        result = _check_option_completeness(q, 0)
        assert result is not None
        assert "C" in result["missing"]
        assert result["found"] == ["A", "B", "D"]

    def test_no_options_flagged(self):
        q = {"question_type": "multiple_choice", "options": []}
        result = _check_option_completeness(q, 0)
        assert result is not None
        assert sorted(result["missing"]) == ["A", "B", "C", "D"]

    def test_non_choice_ignored(self):
        q = {"question_type": "subjective", "options": []}
        assert _check_option_completeness(q, 0) is None


class TestAnswerPresence:
    def test_answer_present_ok(self):
        q = {"question_type": "single_choice", "answer": "A"}
        assert _check_answer_presence(q, 0) is None

    def test_missing_answer_flagged(self):
        q = {"question_type": "single_choice", "answer": ""}
        result = _check_answer_presence(q, 0)
        assert result is not None
        assert result["question_type"] == "single_choice"

    def test_true_false_missing_flagged(self):
        q = {"question_type": "true_false", "answer": "  "}
        result = _check_answer_presence(q, 0)
        assert result is not None

    def test_subjective_no_answer_ok(self):
        q = {"question_type": "subjective", "answer": ""}
        assert _check_answer_presence(q, 0) is None


class TestValidateBatchStructure:
    def test_clean_batch(self):
        questions = [
            {
                "raw_text": f"{i}. 题目{i}",
                "question_type": "single_choice",
                "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}, {"key": "C", "text": "c"}, {"key": "D", "text": "d"}],
                "answer": "A",
                "warnings": [],
            }
            for i in range(1, 4)
        ]
        result = validate_batch_structure(questions)
        stats = result["batch_validation_diagnostics"]["stats"]
        assert stats["number_gap_count"] == 0
        assert stats["incomplete_option_count"] == 0
        assert stats["missing_answer_count"] == 0

    def test_warnings_appended(self):
        questions = [
            {
                "raw_text": "1. 题目",
                "question_type": "single_choice",
                "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
                "answer": "",
                "warnings": [],
            },
        ]
        result = validate_batch_structure(questions)
        q = result["questions"][0]
        assert "incomplete_options: missing C,D" in q["warnings"]
        assert "missing_answer_for_objective_question" in q["warnings"]
