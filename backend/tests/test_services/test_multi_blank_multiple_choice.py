"""Tests for multi_blank_multiple_choice (多空（多选）选择题).

Covers:
- question_type canonical set includes the new code
- per-slot multi-letter parse/serialize/validate
- grading (answer_normalizer) with per-slot set comparison
- capability metadata and alias normalization
"""

from __future__ import annotations

from app.features.multi_blank_choice import (
    normalize_answer_value,
    parse_multi_blank_answer,
    serialize_multi_blank_answer,
    validate_multi_blank_question,
)
from app.features.question_type import (
    CANONICAL_TYPES,
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
    get_question_type_metadata_items,
    is_multi_blank_multiple_type,
    is_multi_blank_type,
    normalize_question_type,
    validate_question_type,
)
from app.utils.answer_normalizer import (
    extract_multi_blank_slot_ids,
    is_answer_correct,
)


# ── question_type registry ──────────────────────────────────────


class TestQuestionTypeRegistry:
    def test_new_code_is_canonical(self):
        assert QT_MULTI_BLANK_MULTIPLE_CHOICE in CANONICAL_TYPES

    def test_validate_accepts_new_code(self):
        assert (
            validate_question_type("multi_blank_multiple_choice")
            == "multi_blank_multiple_choice"
        )

    def test_is_multi_blank_type_covers_both(self):
        assert is_multi_blank_type("multi_blank_choice")
        assert is_multi_blank_type("multi_blank_multiple_choice")
        assert not is_multi_blank_type("single_choice")

    def test_is_multi_blank_multiple_type(self):
        assert is_multi_blank_multiple_type("multi_blank_multiple_choice")
        assert not is_multi_blank_multiple_type("multi_blank_choice")

    def test_chinese_aliases(self):
        assert normalize_question_type("多空多选题")[0] == "multi_blank_multiple_choice"
        assert (
            normalize_question_type("多空（多选）选择题")[0]
            == "multi_blank_multiple_choice"
        )
        assert normalize_question_type("多空单选题")[0] == "multi_blank_choice"

    def test_metadata_capabilities(self):
        items = {
            item["code"]: item for item in get_question_type_metadata_items()
        }
        multi = items["multi_blank_multiple_choice"]
        assert multi["capabilities"]["allows_multiple_answers"] is True
        assert multi["capabilities"]["allows_multi_blank"] is True
        single = items["multi_blank_choice"]
        assert single["capabilities"]["allows_multiple_answers"] is False
        assert single["capabilities"]["allows_multi_blank"] is True


# ── multi-letter slot values ────────────────────────────────────


class TestMultiLetterSlotValues:
    def test_normalize_answer_value(self):
        assert normalize_answer_value("A") == "A"
        assert normalize_answer_value("A,C") == "A,C"
        assert normalize_answer_value("C、A") == "A,C"
        assert normalize_answer_value("ac") == "A,C"
        assert normalize_answer_value("X") == ""
        assert normalize_answer_value("A,X") == "A"

    def test_parse_canonical_multi_letter(self):
        parsed, errors = parse_multi_blank_answer("①:A,C;②:B")
        assert errors == []
        assert parsed == {"①": "A,C", "②": "B"}

    def test_parse_multi_letter_unsorted_canonicalizes(self):
        parsed, errors = parse_multi_blank_answer("①:C,A;②:B")
        assert errors == []
        assert parsed == {"①": "A,C", "②": "B"}

    def test_parse_circled_multi_letter(self):
        parsed, errors = parse_multi_blank_answer("①AC、②D")
        assert errors == []
        assert parsed == {"①": "A,C", "②": "D"}

    def test_parse_single_letter_unchanged(self):
        parsed, errors = parse_multi_blank_answer("①:B;②:D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_parse_digit_slot_multi_letter(self):
        parsed, errors = parse_multi_blank_answer("1:A,C;2:B,D")
        assert errors == []
        assert parsed == {"1": "A,C", "2": "B,D"}

    def test_parse_pair_separator_vs_value_separator(self):
        # comma followed by digit+colon is a pair separator, not a value one
        parsed, errors = parse_multi_blank_answer("1:B,2:D")
        assert errors == []
        assert parsed == {"1": "B", "2": "D"}

    def test_serialize_multi_letter(self):
        assert (
            serialize_multi_blank_answer({"①": "C,A", "②": "B"}, ["①", "②"])
            == "①:A,C;②:B"
        )

    def test_serialize_single_letter_unchanged(self):
        assert (
            serialize_multi_blank_answer({"①": "B", "②": "D"}, ["①", "②"])
            == "①:B;②:D"
        )


# ── validation with multi-letter answers ────────────────────────


class TestValidateMultiLetter:
    def make_group(self, gid, keys):
        return {"id": gid, "options": [{"key": k, "text": f"t_{k}"} for k in keys]}

    def test_valid_multi_letter(self):
        groups = [self.make_group("①", ["A", "B", "C"]), self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:A,C;②:B")
        assert is_valid, errors

    def test_multi_letter_not_in_options(self):
        groups = [self.make_group("①", ["A", "B"]), self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:A,C;②:B")
        assert not is_valid
        assert any("not_in_group_options" in e for e in errors)

    def test_duplicate_letter_deduplicated(self):
        groups = [self.make_group("①", ["A", "B"]), self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:A,A;②:B")
        assert is_valid, errors

    def test_single_letter_still_valid(self):
        groups = [self.make_group("①", ["A", "B"]), self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:B;②:A")
        assert is_valid, errors


# ── grading ──────────────────────────────────────────────────────


class TestGradingMultiBlankMultiple:
    def _content(self):
        return {
            "blank_option_groups": [
                {"id": "①", "options": [{"key": "A"}, {"key": "B"}, {"key": "C"}]},
                {"id": "②", "options": [{"key": "A"}, {"key": "B"}, {"key": "D"}]},
            ]
        }

    def test_correct_multi_letter(self):
        slot_ids = extract_multi_blank_slot_ids(self._content())
        assert is_answer_correct(
            "①:A,C;②:B",
            "①:C,A;②:B",
            "multi_blank_multiple_choice",
            slot_ids=slot_ids,
        )

    def test_wrong_extra_letter(self):
        slot_ids = extract_multi_blank_slot_ids(self._content())
        assert not is_answer_correct(
            "①:A,C;②:B",
            "①:A,C,D;②:B",
            "multi_blank_multiple_choice",
            slot_ids=slot_ids,
        )

    def test_wrong_missing_letter(self):
        slot_ids = extract_multi_blank_slot_ids(self._content())
        assert not is_answer_correct(
            "①:A;②:B",
            "①:A,C;②:B",
            "multi_blank_multiple_choice",
            slot_ids=slot_ids,
        )

    def test_wrong_single_slot_value(self):
        slot_ids = extract_multi_blank_slot_ids(self._content())
        assert not is_answer_correct(
            "①:A,C;②:D",
            "①:A,C;②:B",
            "multi_blank_multiple_choice",
            slot_ids=slot_ids,
        )

    def test_run_together_letters(self):
        slot_ids = extract_multi_blank_slot_ids(self._content())
        assert is_answer_correct(
            "①AC;②B",
            "①:A,C;②:B",
            "multi_blank_multiple_choice",
            slot_ids=slot_ids,
        )

    def test_single_type_still_exact_match(self):
        slot_ids = extract_multi_blank_slot_ids(self._content())
        assert is_answer_correct(
            "①:A;②:B", "①:A;②:B", "multi_blank_choice", slot_ids=slot_ids
        )
        assert not is_answer_correct(
            "①:A,C;②:B", "①:A;②:B", "multi_blank_choice", slot_ids=slot_ids
        )
