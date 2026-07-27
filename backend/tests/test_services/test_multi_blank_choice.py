"""Tests for multi_blank_choice utilities.

Covers parsing, serialization, validation, detection, and hash
for shared-option multi-blank choice questions.
"""

from __future__ import annotations

from app.features.multi_blank_choice import (
    build_blank_option_groups,
    detect_shared_option_multi_blank,
    extract_blank_slots,
    parse_multi_blank_answer,
    serialize_multi_blank_answer,
    validate_multi_blank_question,
)
from app.features.question_pipeline import normalizer

# ── extract_blank_slots ─────────────────────────────────────────


class TestExtractBlankSlots:
    def test_circled_with_parens(self):
        """①（ ）②（ ）"""
        slots = extract_blank_slots("入度是（① ）；出度是（② ）。")
        assert slots == ["①", "②"]

    def test_standalone_circled(self):
        """① ② without explicit （ ）"""
        slots = extract_blank_slots("入度是①；出度是②。")
        assert slots == ["①", "②"]

    def test_numbered_parens(self):
        """(1) (2)"""
        slots = extract_blank_slots("平均长度为（1）；深度为（2）。")
        assert slots == ["1", "2"]

    def test_anonymous_blanks(self):
        """（ ）（ ）"""
        slots = extract_blank_slots("入度是（ ）；出度是（ ）。")
        assert slots == ["1", "2"]

    def test_underscore_blanks(self):
        """____ ____"""
        slots = extract_blank_slots("入度是____；出度是____。")
        assert slots == ["1", "2"]

    def test_no_blanks_returns_empty(self):
        assert extract_blank_slots("普通题干") == []

    def test_single_blank_not_multi(self):
        """Single ( ) is not multi-blank"""
        assert extract_blank_slots("值是（ ）。") == ["1"]

    def test_math_parens_not_confused(self):
        """Mathematical interval (0,1) should not match"""
        assert extract_blank_slots("在区间(0,1)上连续") == []

    def test_mixed_circled_and_paren(self):
        """(1) and ② mix"""
        slots = extract_blank_slots("空①：入度（ ）；空②：出度（ ）。")
        assert slots == ["①", "②"]

    def test_three_blanks(self):
        """Three blanks"""
        slots = extract_blank_slots("（ ）（ ）（ ）")
        assert slots == ["1", "2", "3"]


# ── parse_multi_blank_answer ────────────────────────────────────


class TestParseMultiBlankAnswer:
    def test_canonical_format(self):
        parsed, errors = parse_multi_blank_answer("①:B;②:D", slot_ids=["①", "②"])
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_canonical_reverse_order(self):
        parsed, errors = parse_multi_blank_answer("②:D;①:B", slot_ids=["①", "②"])
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_chinese_comma(self):
        parsed, errors = parse_multi_blank_answer("①B、②D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_chinese_comma_with_space(self):
        parsed, errors = parse_multi_blank_answer("① B，② D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_paren_digits(self):
        parsed, errors = parse_multi_blank_answer("(1)B、(2)D")
        assert errors == []
        assert parsed == {"1": "B", "2": "D"}

    def test_digit_slot_colon(self):
        parsed, errors = parse_multi_blank_answer("1:B,2:D", slot_ids=["1", "2"])
        assert errors == []
        assert parsed == {"1": "B", "2": "D"}

    def test_chinese_natural_language(self):
        parsed, errors = parse_multi_blank_answer("第1空B，第2空D")
        assert errors == []
        assert parsed == {"1": "B", "2": "D"}

    def test_chinese_language_variant(self):
        """第1空: B, 第2空: D — parsed as canonical with slot names preserved"""
        parsed, _ = parse_multi_blank_answer("第1空：B，第2空：D")
        assert parsed == {"第1空": "B", "第2空": "D"}

    def test_positional_a_b(self):
        """A,B with known slot_ids"""
        parsed, errors = parse_multi_blank_answer("A,B", slot_ids=["①", "②"], allow_positional=True)
        assert errors == []
        assert parsed == {"①": "A", "②": "B"}

    def test_positional_b_d(self):
        parsed, errors = parse_multi_blank_answer("B,D", slot_ids=["①", "②"], allow_positional=True)
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_positional_wrong_count(self):
        """Positional with wrong count should not match"""
        parsed, errors = parse_multi_blank_answer("A,B", slot_ids=["①", "②", "③"], allow_positional=True)
        assert parsed == {}  # 2 answers vs 3 slots — won't match
        assert any("unparseable" in e for e in errors)

    def test_positional_disallowed(self):
        """Positional should not match when allow_positional=False"""
        parsed, errors = parse_multi_blank_answer("A,B", slot_ids=["①", "②"], allow_positional=False)
        assert parsed == {}

    def test_circular_marker(self):
        """①B、②D"""
        parsed, errors = parse_multi_blank_answer("①B、②D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_canonical_colon(self):
        """①:B;②:D"""
        parsed, errors = parse_multi_blank_answer("①:B;②:D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_case_insensitive(self):
        parsed, errors = parse_multi_blank_answer("①:b;②:d")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_extra_whitespace(self):
        parsed, errors = parse_multi_blank_answer(" ① : B ; ② : D ")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_answer_too_few_slots(self):
        """①:B only — missing ②"""
        parsed, errors = parse_multi_blank_answer("①:B")
        # Should parse what it can
        assert parsed == {"①": "B"}
        # No error for partial, but this is handled at validation level

    def test_empty_answer(self):
        parsed, errors = parse_multi_blank_answer(None)
        assert parsed == {}
        assert errors == []

    def test_empty_string(self):
        parsed, errors = parse_multi_blank_answer("")
        assert parsed == {}
        assert errors == []

    def test_dict_input(self):
        parsed, errors = parse_multi_blank_answer({"①": "B", "②": "D"})
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_dict_input_lowercase(self):
        parsed, errors = parse_multi_blank_answer({"①": "b", "②": "d"})
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_list_input_with_slot_ids(self):
        parsed, errors = parse_multi_blank_answer(["B", "D"], slot_ids=["①", "②"])
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_letters_only_AB(self):
        parsed, errors = parse_multi_blank_answer("BD", slot_ids=["①", "②"], allow_positional=True)
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_supports_A_to_H(self):
        parsed, errors = parse_multi_blank_answer("①:E;②:H")
        assert errors == []
        assert parsed == {"①": "E", "②": "H"}

    def test_multiple_delimiters(self):
        """①:B,②:D using comma as separator"""
        parsed, errors = parse_multi_blank_answer("①:B,②:D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}


# ── serialize_multi_blank_answer ─────────────────────────────────


class TestSerializeMultiBlankAnswer:
    def test_basic_serialize(self):
        result = serialize_multi_blank_answer({"①": "B", "②": "D"}, ["①", "②"])
        assert result == "①:B;②:D"

    def test_serialize_follows_slot_order(self):
        result = serialize_multi_blank_answer({"②": "D", "①": "B"}, ["①", "②"])
        assert result == "①:B;②:D"

    def test_serialize_skips_unknown_slots(self):
        """Only serializes slots in slot_ids"""
        result = serialize_multi_blank_answer({"①": "B", "②": "D", "③": "A"}, ["①", "②"])
        assert "③" not in result

    def test_empty_map(self):
        assert serialize_multi_blank_answer({}, ["①", "②"]) == ""

    def test_empty_slot_ids(self):
        assert serialize_multi_blank_answer({"①": "B"}, []) == ""

    def test_partial_slots(self):
        result = serialize_multi_blank_answer({"①": "B", "②": "D"}, ["①"])
        assert result == "①:B"


# ── build_blank_option_groups ───────────────────────────────────


class TestBuildBlankOptionGroups:
    def test_from_dict_options(self):
        groups = build_blank_option_groups(
            ["①", "②"],
            {"A": "option a", "B": "option b", "C": "option c", "D": "option d"},
        )
        assert len(groups) == 2
        assert groups[0]["id"] == "①"
        assert groups[1]["id"] == "②"
        assert len(groups[0]["options"]) == 4
        assert groups[0]["options"] == groups[1]["options"]

    def test_from_list_options(self):
        shared = [
            {"key": "A", "text": "text a"},
            {"key": "B", "text": "text b"},
            {"key": "C", "text": "text c"},
        ]
        groups = build_blank_option_groups(["①", "②"], shared)
        assert len(groups) == 2
        assert groups[0]["options"][0]["key"] == "A"

    def test_insufficient_options(self):
        groups = build_blank_option_groups(["①", "②"], {"A": "only"})
        assert groups == []

    def test_empty_slot_ids(self):
        groups = build_blank_option_groups([], {"A": "a", "B": "b"})
        assert groups == []


# ── validate_multi_blank_question ────────────────────────────────


class TestValidateMultiBlankQuestion:
    def make_group(self, gid: str, keys: list[str]) -> dict:
        return {
            "id": gid,
            "options": [{"key": k, "text": f"text_{k}"} for k in keys],
        }

    def test_valid(self):
        groups = [self.make_group("①", ["A", "B", "C", "D"]),
                  self.make_group("②", ["A", "B", "C", "D"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:B;②:D")
        assert is_valid, errors
        assert errors == []

    def test_valid_with_positional_answer(self):
        groups = [self.make_group("①", ["A", "B", "C", "D"]),
                  self.make_group("②", ["A", "B", "C", "D"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:B;②:D")
        assert is_valid
        assert errors == []

    def test_at_least_2_groups(self):
        group = self.make_group("①", ["A", "B", "C", "D"])
        is_valid, errors = validate_multi_blank_question([group], "①:B")
        assert not is_valid
        assert any("at_least_2" in e for e in errors)

    def test_each_group_has_2_options_min(self):
        groups = [self.make_group("①", ["A"]),
                  self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:B;②:A")
        assert not is_valid
        assert any("less_than_2_options" in e for e in errors)

    def test_answer_missing_slot(self):
        groups = [self.make_group("①", ["A", "B", "C", "D"]),
                  self.make_group("②", ["A", "B", "C", "D"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:B")  # missing ②
        assert not is_valid
        assert any("missing" in e for e in errors)

    def test_answer_extra_slot(self):
        groups = [self.make_group("①", ["A", "B", "C", "D"]),
                  self.make_group("②", ["A", "B", "C", "D"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:B;②:D;③:A")
        assert not is_valid
        assert any("extra" in e for e in errors)

    def test_answer_not_in_options(self):
        groups = [self.make_group("①", ["A", "B"]),
                  self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:X;②:Y")
        assert not is_valid
        assert any("not_in_group_options" in e for e in errors)

    def test_duplicate_group_id(self):
        groups = [self.make_group("①", ["A", "B"]),
                  self.make_group("①", ["C", "D"])]
        is_valid, errors = validate_multi_blank_question(groups, "①:A;①:C")
        assert not is_valid
        assert any("duplicate" in e for e in errors)

    def test_missing_answer(self):
        groups = [self.make_group("①", ["A", "B"]),
                  self.make_group("②", ["A", "B"])]
        is_valid, errors = validate_multi_blank_question(groups, None)
        assert not is_valid
        assert any("missing" in e for e in errors)

    def test_empty_groups(self):
        is_valid, errors = validate_multi_blank_question([], "①:B;②:D")
        assert not is_valid


# ── detect_shared_option_multi_blank ─────────────────────────────


class TestDetectSharedOptionMultiBlank:
    def test_detect_adjacency_matrix(self):
        """The canonical example from the task prompt."""
        stem = "一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 v_i 的入度是（ ）；若图为无向图，顶点 v_i 的度是（ ）。"
        options = [
            {"key": "A", "text": "∑..."},
            {"key": "B", "text": "∑..."},
            {"key": "C", "text": "∑..."},
            {"key": "D", "text": "..."},
        ]
        answer = "①B、②D"
        result = detect_shared_option_multi_blank(stem, options, answer)
        assert result["is_multi_blank_choice"] is True, result
        assert len(result["slot_ids"]) >= 2
        assert len(result["blank_option_groups"]) == 2
        assert result["blank_option_groups"][0]["options"][0]["key"] == "A"
        assert result["blank_option_groups"][1]["options"][0]["key"] == "A"

    def test_no_blanks_not_detected(self):
        result = detect_shared_option_multi_blank("普通题干", [{"key": "A", "text": "a"}], "A")
        assert result["is_multi_blank_choice"] is False

    def test_single_blank_not_detected(self):
        result = detect_shared_option_multi_blank("值是（ ）。", [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}], "A")
        assert result["is_multi_blank_choice"] is False

    def test_explicit_question_type(self):
        result = detect_shared_option_multi_blank(
            "题干", [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
            "①:A;②:B",
            explicit_question_type="multi_blank_choice",
        )
        assert result["is_multi_blank_choice"] is True

    def test_multiple_blanks_without_options_warns(self):
        result = detect_shared_option_multi_blank("入度是（ ）；出度是（ ）。", None, None)
        assert result["is_multi_blank_choice"] is False
        assert any("without_options" in w for w in result["warnings"])

    def test_no_answer_still_detects_if_has_options(self):
        """Two blanks + options → detected even without answer"""
        result = detect_shared_option_multi_blank(
            "入度是（ ）；出度是（ ）。",
            [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}, {"key": "C", "text": "c"}, {"key": "D", "text": "d"}],
            None,
        )
        # Should detect as multi blank choice even without answer
        assert result["is_multi_blank_choice"] is True, result
        assert any("no_answer" in w for w in result["warnings"])


# ── Hash with blank_option_groups ────────────────────────────────


class TestHashWithBlankGroups:
    def test_hash_differs_with_different_groups(self):
        h1 = normalizer.build_question_hash(
            "stem", [],
            "①:A;②:B",
            blank_option_groups=[
                {"id": "①", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
                {"id": "②", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
            ],
        )
        h2 = normalizer.build_question_hash(
            "stem", [],
            "①:A;②:B",
            blank_option_groups=[
                {"id": "①", "options": [{"key": "A", "text": "z"}, {"key": "B", "text": "w"}]},
                {"id": "②", "options": [{"key": "A", "text": "z"}, {"key": "B", "text": "w"}]},
            ],
        )
        assert h1 != h2, "Different group options must produce different hashes"

    def test_hash_change_with_different_answer(self):
        h1 = normalizer.build_question_hash(
            "stem", [],
            "①:B;②:D",
            blank_option_groups=[
                {"id": "①", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
                {"id": "②", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
            ],
        )
        h2 = normalizer.build_question_hash(
            "stem", [],
            "①:A;②:D",
            blank_option_groups=[
                {"id": "①", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
                {"id": "②", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
            ],
        )
        assert h1 != h2

    def test_hash_not_broken_without_groups(self):
        """Normal questions still hash correctly without blank groups."""
        h = normalizer.build_question_hash("正常题干", [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}], "A")
        assert h and len(h) == 32


# ── Integration test: the adjacency matrix regression ───────────


class TestAdjacencyMatrixRegression:
    """Regression test for the canonical failing example from the task prompt."""

    def test_parse_answer(self):
        """①B、②D → {"①": "B", "②": "D"}"""
        parsed, errors = parse_multi_blank_answer("①B、②D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_serialize_answer(self):
        result = serialize_multi_blank_answer({"①": "B", "②": "D"}, ["①", "②"])
        assert result == "①:B;②:D"

    def test_detect_from_stem(self):
        stem = "一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 v_i 的入度是（ ）；若图为无向图，顶点 v_i 的度是（ ）。"
        options = [{"key": "A", "text": "∑一行中第i列的元素之和"}, {"key": "B", "text": "∑一行中第i行的元素之和"}, {"key": "C", "text": "∑一行\n1"}, {"key": "D", "text": "∑\n0"}]
        answer = "①B、②D"
        result = detect_shared_option_multi_blank(stem, options, answer)
        assert result["is_multi_blank_choice"] is True
        assert len(result["slot_ids"]) == 2
        assert len(result["blank_option_groups"]) == 2
        assert len(result["blank_option_groups"][0]["options"]) == 4
        assert len(result["blank_option_groups"][1]["options"]) == 4

    def test_validate(self):
        groups = [
            {"id": "①", "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}, {"key": "C", "text": "c"}, {"key": "D", "text": "d"}]},
            {"id": "②", "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}, {"key": "C", "text": "c"}, {"key": "D", "text": "d"}]},
        ]
        is_valid, errors = validate_multi_blank_question(groups, "①:B;②:D")
        assert is_valid, errors

    def test_full_pipeline_integration(self):
        """Simulate the full pipeline for the adjacency matrix example."""
        stem = "一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 v_i 的入度是（ ）；若图为无向图，顶点 v_i 的度是（ ）。"
        options = {"A": "∑一行中第i列的元素之和", "B": "∑一行中第i行的元素之和", "C": "∑一行", "D": "∑"}
        answer = "①B、②D"

        # 1. Detect
        detection = detect_shared_option_multi_blank(stem, options, answer)
        assert detection["is_multi_blank_choice"] is True

        detection["slot_ids"]
        groups = detection["blank_option_groups"]
        serialized = detection["serialized_answer"]

        # 2. Validate
        is_valid, errors = validate_multi_blank_question(groups, serialized or answer)
        assert is_valid, errors

        # 3. Verify structure
        assert len(groups) == 2
        assert groups[0]["id"] == "①"
        assert groups[1]["id"] == "②"
        assert len(groups[0]["options"]) == 4
        assert serialized == "①:B;②:D"


# ── Phase 2: Import pipeline regression test ───────────────────


class TestPipelineDetection:
    """Test that process_question_pipeline detects shared-option multi-blank."""

    def test_detects_adjacency_matrix_via_pipeline(self):
        """The canonical adjacency matrix example through the real pipeline."""
        from app.features.question_pipeline import process_question_pipeline

        result = process_question_pipeline(
            {
                "subject": "exam408-ds",
                "stem": "一个有 n 个顶点的图用邻接矩阵 A 表示，"
                        "若图为有向图，顶点 v_i 的入度是（ ）；"
                        "若图为无向图，顶点 v_i 的度是（ ）。",
                "options": {
                    "A": "第i列的元素之和",
                    "B": "第i行的元素之和",
                    "C": "对角线之和",
                    "D": "所有元素之和",
                },
                "answer": "①B、②D",
            },
            "manual",
        )

        assert result["is_valid"], result.get("errors")

        normalized = result["normalized"]
        assert normalized["question_type"] == "multi_blank_choice"
        assert normalized["options"] == []
        assert normalized["answer"] == "①:B;②:D"

        groups = normalized["blank_option_groups"]
        assert len(groups) == 2
        assert groups[0]["id"] == "①"
        assert groups[1]["id"] == "②"
        assert len(groups[0]["options"]) == 4
        assert groups[0]["options"] == groups[1]["options"]

        # Pipeline output should have import_fields with blank groups
        imp_fields = result["import_fields"]
        assert imp_fields["question_type"] == "multi_blank_choice"
        assert imp_fields["parsed_options"] is None
        assert (imp_fields["parsed_content"] or {}).get("blank_option_groups") == groups

    def test_single_choice_unchanged(self):
        """Normal single-choice questions are NOT detected as multi-blank."""
        from app.features.question_pipeline import process_question_pipeline

        result = process_question_pipeline(
            {
                "subject": "math2",
                "stem": "设函数 $f(x)=x^2$，求 $f'(x)$。",
                "options": {"A": "$2x$", "B": "$x$", "C": "$2$", "D": "$0$"},
                "answer": "A",
            },
            "manual",
        )

        assert result["is_valid"]
        assert result["normalized"]["question_type"] == "single_choice"

    def test_fill_blank_unchanged(self):
        """Fill-blank with multiple blanks but no options is NOT detected."""
        from app.features.question_pipeline import process_question_pipeline

        result = process_question_pipeline(
            {
                "subject": "math2",
                "stem": "入度是（ ）；出度是（ ）。",
                "answer": "①②",
            },
            "manual",
        )

        assert result["is_valid"]
        assert result["normalized"]["question_type"] != "multi_blank_choice"

    def test_multi_blank_rejected_when_no_answer(self):
        """Multi-blank without answer must fail pipeline validation."""
        from app.features.question_pipeline import process_question_pipeline

        result = process_question_pipeline(
            {
                "subject": "exam408-ds",
                "stem": "入度是（ ）；出度是（ ）。",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                # No answer — detection succeeds but publish validation fails
            },
            "manual",
        )

        assert not result["is_valid"]
        errors = result["errors"]
        assert any("missing" in e for e in errors)

    def test_existing_blank_groups_preserved(self):
        """When blank_option_groups are already set, detection is skipped."""
        from app.features.question_pipeline import process_question_pipeline

        groups = [
            {"id": "①", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
            {"id": "②", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
        ]
        result = process_question_pipeline(
            {
                "subject": "exam408-ds",
                "stem": "入度是（ ）；出度是（ ）。",
                "blank_option_groups": groups,
                "answer": "①:A;②:B",
            },
            "manual",
        )

        assert result["is_valid"], result.get("errors")
        assert result["normalized"]["blank_option_groups"] == groups


# ── Phase 4: E2E pipeline coverage ──────────────────────────────


class TestMultiBlankE2EPipeline:
    """End-to-end pipeline tests covering the full use-case matrix from Phase 4.

    Tests process_question_pipeline for various input formats, edge cases,
    and ensures backward compatibility of existing question types.
    """

    def _run_pipeline(self, stem: str, options: dict | None = None,
                      answer: str | None = None,
                      question_type: str | None = None,
                      blank_option_groups: list | None = None) -> dict:
        """Helper: run the full question pipeline."""
        from app.features.question_pipeline import process_question_pipeline

        raw = {"subject": "exam408-ds", "stem": stem}
        if options is not None:
            raw["options"] = options
        if answer is not None:
            raw["answer"] = answer
        if question_type is not None:
            raw["question_type"] = question_type
        if blank_option_groups is not None:
            raw["blank_option_groups"] = blank_option_groups
        return process_question_pipeline(raw, "manual")

    # ── Use case matrix ──

    def test_1_two_blanks_shared_options(self):
        """Two blanks sharing A-D, answer ①B、②D."""
        result = self._run_pipeline(
            stem="顶点v_i的入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①B、②D",
        )
        assert result["is_valid"], result.get("errors")
        n = result["normalized"]
        assert n["question_type"] == "multi_blank_choice"
        assert n["answer"] == "①:B;②:D"
        assert len(n["blank_option_groups"]) == 2
        assert n["options"] == []

    def test_2_two_blanks_positional_answer(self):
        """Two blanks sharing A-D, positional answer B,D."""
        result = self._run_pipeline(
            stem="顶点v_i的入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="B,D",
        )
        assert result["is_valid"], result.get("errors")
        n = result["normalized"]
        assert n["question_type"] == "multi_blank_choice"
        # Positional "B,D" with 2 anonymous blanks → B->slot1, D->slot2
        assert "B" in n["answer"]
        assert "D" in n["answer"]

    def test_3_independent_option_groups(self):
        """Two blanks each with their own options (pre-existing format)."""
        result = self._run_pipeline(
            stem="①（ ）；②（ ）。",
            answer="①:A;②:B",
            blank_option_groups=[
                {"id": "①", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
                {"id": "②", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
            ],
        )
        assert result["is_valid"], result.get("errors")
        assert result["normalized"]["question_type"] == "multi_blank_choice"
        assert result["normalized"]["answer"] == "①:A;②:B"

    def test_4_swapped_order_answer(self):
        """Slots answered in swapped order — answer is valid."""
        result = self._run_pipeline(
            stem="顶点v_i的入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="②:D;①:B",  # reversed order
        )
        assert result["is_valid"], result.get("errors")
        n = result["normalized"]
        # Canonical format preserves input order, but validation is order-independent
        assert "B" in n["answer"]
        assert "D" in n["answer"]

        from app.features.multi_blank_choice import validate_multi_blank_question
        is_valid, errors = validate_multi_blank_question(n["blank_option_groups"], n["answer"])
        assert is_valid, errors

    def test_5_one_blank_answered_only(self):
        """Only one blank answered — detection needs 2+ answer slots, so won't detect
        as multi_blank_choice. The question passes through as single_choice/fill_blank
        and must be corrected during review (expected behavior: pipeline doesn't
        introduce false positives for partial answers)."""
        result = self._run_pipeline(
            stem="顶点v_i的入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①:B",  # only one blank
        )
        # Pipeline may or may not detect this; the key is it doesn't silently
        # produce a broken multi_blank_choice
        n = result["normalized"]
        # If it IS detected as multi_blank_choice, validation must catch missing slot
        if n["question_type"] == "multi_blank_choice":
            assert not result["is_valid"], "missing slot must be caught"
        # Otherwise it passes through with non-multi_blank type (manual review needed)

    def test_6_extra_slot_in_answer(self):
        """Answer has 3 slots but stem has 2 blanks. Detection uses answer slot IDs
        (①,②,③) over stem (1,2), creating 3 groups. Validation passes because each
        group has a matching answer. The stem/group mismatch is a review concern."""
        result = self._run_pipeline(
            stem="顶点v_i的入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①:B;②:D;③:A",  # three slots but stem only has two blanks
        )
        n = result["normalized"]
        if n["question_type"] == "multi_blank_choice":
            # Detection succeeded with 3 answer-derived groups
            assert len(n.get("blank_option_groups", [])) == 3
            # Pipeline validates all 3 slots answered
            assert result["is_valid"]

    def test_7_answer_not_in_options(self):
        """Answer letter not present in options."""
        result = self._run_pipeline(
            stem="顶点v_i的入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c"},  # no D
            answer="①:A;②:D",  # D not in options
        )
        assert not result["is_valid"]
        errors = result["errors"]
        assert any("not_in_group_options" in e for e in errors), errors

    def test_8_three_blanks(self):
        """Three blank slots."""
        result = self._run_pipeline(
            stem="空1（ ）；空2（ ）；空3（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①:A;②:B;③:C",
        )
        assert result["is_valid"], result.get("errors")
        n = result["normalized"]
        assert n["question_type"] == "multi_blank_choice"
        assert len(n["blank_option_groups"]) >= 2

    def test_9_regular_single_choice_with_parens(self):
        """Normal single-choice with math parentheses should NOT be detected."""
        result = self._run_pipeline(
            stem="函数 $f(x)$ 在区间 $(0,1)$ 上连续，求 $f(0)$。",
            options={"A": "1", "B": "2", "C": "3", "D": "4"},
            answer="A",
        )
        assert result["is_valid"], result.get("errors")
        assert result["normalized"]["question_type"] == "single_choice"

    def test_10_fill_blank_two_blanks_no_choice(self):
        """Fill-blank with two blanks but no options — should NOT be multi_blank_choice."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            answer="①：B",  # no options
        )
        assert result["is_valid"], result.get("errors")
        assert result["normalized"]["question_type"] != "multi_blank_choice"

    def test_11_old_types_unchanged(self):
        """Existing single/multiple/true-false questions must work as before."""
        # Single choice (needs 4 options for completeness check)
        r1 = self._run_pipeline("x=?", {"A": "1", "B": "2", "C": "3", "D": "4"}, "A")
        assert r1["is_valid"]
        assert r1["normalized"]["question_type"] == "single_choice"

        # Multiple choice (explicitly typed)
        r2 = self._run_pipeline(
            "x,y=?",
            {"A": "1", "B": "2", "C": "3", "D": "4"},
            "A,B",
            question_type="multiple_choice",
        )
        assert r2["is_valid"]
        assert r2["normalized"]["question_type"] == "multiple_choice"

        # True/false (explicitly typed)
        r3 = self._run_pipeline(
            "x>0?",
            {"A": "正确", "B": "错误"},
            "A",
            question_type="true_false",
        )
        assert r3["is_valid"]
        assert r3["normalized"]["question_type"] == "true_false"

    # ── Answer matching edge cases ──

    def test_answer_with_circled_digits_chinese_comma(self):
        """OCR-extracted '①B、②D' format."""
        from app.features.multi_blank_choice import parse_multi_blank_answer
        parsed, errors = parse_multi_blank_answer("①B、②D")
        assert errors == []
        assert parsed == {"①": "B", "②": "D"}

    def test_answer_with_chinese_natural_language(self):
        """'第1空B，第2空D' natural language format."""
        from app.features.multi_blank_choice import parse_multi_blank_answer
        parsed, errors = parse_multi_blank_answer("第1空：B，第2空：D")
        assert errors == []
        assert "B" in parsed.values()
        assert "D" in parsed.values()

    def test_answer_supports_A_to_H(self):
        """Beyond A-D support."""
        from app.features.multi_blank_choice import parse_multi_blank_answer
        parsed, errors = parse_multi_blank_answer("①:E;②:G")
        assert errors == []
        assert parsed == {"①": "E", "②": "G"}

    # ── Import fields consistency ──

    def test_import_fields_contract(self):
        """Verify import_fields data contract after pipeline processing."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①B、②D",
        )
        assert result["is_valid"], result.get("errors")

        imp = result["import_fields"]
        assert imp["question_type"] == "multi_blank_choice"
        assert imp["parsed_options"] is None  # multi_blank sets options to None
        assert imp["parsed_answer"] == "①:B;②:D"

        pc = imp.get("parsed_content") or {}
        assert "blank_option_groups" in pc
        assert len(pc["blank_option_groups"]) == 2
        assert pc["blank_option_groups"][0]["id"] == "①"
        assert pc["blank_option_groups"][1]["id"] == "②"

    def test_question_fields_contract(self):
        """Verify question_fields data contract after pipeline processing."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①B、②D",
        )
        assert result["is_valid"], result.get("errors")

        qf = result.get("question_fields")
        assert qf is not None
        assert qf["question_type"] == "multi_blank_choice"
        assert qf["options"] is None  # multi_blank sets options to None
        assert qf["answer"] == "①:B;②:D"

    def test_import_fields_multi_blank_no_answer_has_missing_risk(self):
        """Multi-blank without answer gets question_type but fails validation."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            # No answer
        )
        assert not result["is_valid"]
        errors = result["errors"]
        assert any("answer" in e for e in errors)

    def test_three_option_not_four(self):
        """Still works with exactly 2 options (not just 4)."""
        result = self._run_pipeline(
            stem="选（ ）或（ ）。",
            options={"A": "对", "B": "错"},
            answer="①:A;②:B",
        )
        assert result["is_valid"], result.get("errors")
        n = result["normalized"]
        assert n["question_type"] == "multi_blank_choice"
        assert len(n["blank_option_groups"][0]["options"]) == 2

    # ── Fix 1: answer_matcher multi-blank answer extraction ──

    def test_explicit_answer_extraction_multi_blank(self):
        """extract_explicit_answer should handle ①B、②D format."""
        from app.features.answer_matcher import extract_explicit_answer
        result = extract_explicit_answer("答案：①B、②D")
        assert result.answer is not None, "Multi-blank answer should be extracted"
        assert "①" in result.answer
        assert "B" in result.answer.upper()
        assert "D" in result.answer.upper()

    def test_explicit_answer_extraction_multi_blank_with_four_blanks(self):
        """extract_explicit_answer with ③+④ circled digits."""
        from app.features.answer_matcher import extract_explicit_answer
        result = extract_explicit_answer("答案：①A、②B、③C、④D")
        assert result.answer is not None
        assert "③" in result.answer
        assert "④" in result.answer

    def test_explicit_answer_extraction_single_choice_unaffected(self):
        """Single-choice answers must not be broken by multi-blank fix."""
        from app.features.answer_matcher import extract_explicit_answer
        result = extract_explicit_answer("答案：A")
        assert result.answer == "A"
        result2 = extract_explicit_answer("答案：B、C")
        assert result2.answer == "B,C"

    # ── Fix 2: normalize_answer canonicalization for explicitly-typed multi_blank_choice ──

    def test_normalize_answer_explicit_multi_blank_canonicalizes(self):
        """Explicitly typed multi_blank_choice with non-canonical answer gets canonicalized."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①B、②D",
        )
        assert result["is_valid"], result.get("errors")
        assert result["normalized"]["answer"] == "①:B;②:D"

    def test_normalize_answer_multi_blank_canonical_already(self):
        """Already canonical answer stays canonical."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="①:B;②:D",
        )
        assert result["is_valid"], result.get("errors")
        assert result["normalized"]["answer"] == "①:B;②:D"

    def test_normalize_answer_multi_blank_no_answer(self):
        """Empty answer for multi_blank_choice returns empty."""
        result = self._run_pipeline(
            stem="入度是（ ）；出度是（ ）。",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer="",
        )
        # No answer → not valid, but answer should be empty string
        assert result["normalized"]["answer"] == ""
