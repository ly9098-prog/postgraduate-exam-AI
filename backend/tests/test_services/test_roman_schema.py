"""Tests for roman_schema.py — shared Roman numeral constants, schemas, and utilities."""

from app.features.roman_schema import (
    _RE_ROMAN_SUBITEM_MARKER,
    _ROMAN_TO_VALUE,
    _VALUE_TO_ROMAN,
    DUPLICATE,
    GAP,
    SEQUENCE_BREAK,
    apply_roman_fix,
    build_roman_anomaly,
    classify_roman_issue,
    generate_digit_confusion_candidates,
    generate_duplicate_candidates,
    generate_gap_candidates,
    has_roman_subitem_list,
)


class TestConstants:
    def test_roman_to_value_all_keys(self):
        # ASCII keys must be present (dict may also include Unicode + mixed variants)
        for k, v in {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
                     "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}.items():
            assert _ROMAN_TO_VALUE.get(k) == v, f"missing or wrong value for {k}"

    def test_value_to_roman_all_keys(self):
        assert _VALUE_TO_ROMAN[1] == "I"
        assert _VALUE_TO_ROMAN[2] == "II"
        assert _VALUE_TO_ROMAN[3] == "III"
        assert _VALUE_TO_ROMAN[4] == "IV"
        assert _VALUE_TO_ROMAN[5] == "V"
        assert _VALUE_TO_ROMAN[10] == "X"

    def test_regex_matches_tokens(self):
        assert _RE_ROMAN_SUBITEM_MARKER.search("I. 顺序存储")
        assert _RE_ROMAN_SUBITEM_MARKER.search("II. 链式存储")
        assert _RE_ROMAN_SUBITEM_MARKER.search("III. 循环链表")
        assert _RE_ROMAN_SUBITEM_MARKER.search("IV. 有序链表")
        assert _RE_ROMAN_SUBITEM_MARKER.search("V. 单链表")

    def test_regex_longest_match_first(self):
        markers = _RE_ROMAN_SUBITEM_MARKER.findall("VIII. 8级 III. 3级")
        assert markers[0].startswith("VIII")
        assert markers[1].startswith("III")

    def test_regex_rejects_word_boundary(self):
        assert not _RE_ROMAN_SUBITEM_MARKER.search("PIVOT table")
        assert not _RE_ROMAN_SUBITEM_MARKER.search("LIVID response")

    def test_regex_matches_unicode_roman(self):
        assert _RE_ROMAN_SUBITEM_MARKER.search("Ⅰ. Unicode I")
        assert _RE_ROMAN_SUBITEM_MARKER.search("Ⅱ. Unicode II")
        assert _RE_ROMAN_SUBITEM_MARKER.search("Ⅲ. Unicode III")
        assert _RE_ROMAN_SUBITEM_MARKER.search("Ⅳ. Unicode IV")
        assert _RE_ROMAN_SUBITEM_MARKER.search("Ⅴ. Unicode V")

    def test_regex_matches_mixed_roman(self):
        assert _RE_ROMAN_SUBITEM_MARKER.search("IⅡ. Mixed I+II")
        assert _RE_ROMAN_SUBITEM_MARKER.search("IⅢ. Mixed I+III")
        assert _RE_ROMAN_SUBITEM_MARKER.search("IⅣ. Mixed I+IV")

    def test_unicode_roman_value_mapping(self):
        assert _ROMAN_TO_VALUE["Ⅰ"] == 1
        assert _ROMAN_TO_VALUE["Ⅱ"] == 2
        assert _ROMAN_TO_VALUE["Ⅲ"] == 3
        assert _ROMAN_TO_VALUE["Ⅳ"] == 4
        assert _ROMAN_TO_VALUE["Ⅴ"] == 5
        assert _ROMAN_TO_VALUE["IⅡ"] == 2
        assert _ROMAN_TO_VALUE["IⅢ"] == 3


class TestHasRomanSubitemList:
    def test_no_roman_markers(self):
        assert not has_roman_subitem_list("这是普通文本")

    def test_single_roman_marker(self):
        assert not has_roman_subitem_list("I. 只有一个标记")

    def test_two_different_markers(self):
        assert has_roman_subitem_list("I. 第一\nII. 第二")

    def test_repeated_same_marker(self):
        assert not has_roman_subitem_list("I. 第一\nI. 又一个第一")

    def test_five_markers(self):
        text = "I. 一\nII. 二\nIII. 三\nIV. 四\nV. 五"
        assert has_roman_subitem_list(text)

    def test_empty_text(self):
        assert not has_roman_subitem_list("")
        assert not has_roman_subitem_list(None)  # type: ignore


class TestClassifyRomanIssue:
    def test_clean_sequence(self):
        assert classify_roman_issue(["I", "II", "III"], [1, 2, 3]) == ""

    def test_duplicate(self):
        assert classify_roman_issue(["I", "II", "II", "IV"], [1, 2, 2, 4]) == DUPLICATE

    def test_gap(self):
        assert classify_roman_issue(["I", "II", "IV", "V"], [1, 2, 4, 5]) == GAP

    def test_sequence_break(self):
        assert classify_roman_issue(["II", "I", "III"], [2, 1, 3]) == SEQUENCE_BREAK

    def test_short_sequence(self):
        assert classify_roman_issue(["I"], [1]) == ""
        assert classify_roman_issue([], []) == ""


class TestBuildRomanAnomaly:
    def test_minimal_anomaly(self):
        a = build_roman_anomaly(0, "stem", DUPLICATE, ["I", "II", "II"], [1, 2, 2])
        assert a["index"] == 0
        assert a["source"] == "stem"
        assert a["issue_type"] == DUPLICATE
        assert a["found_tokens"] == ["I", "II", "II"]
        assert a["found_values"] == [1, 2, 2]

    def test_with_snippet_and_candidates(self):
        a = build_roman_anomaly(
            0, "stem", DUPLICATE,
            ["I", "II", "II"], [1, 2, 2],
            text_snippet="语境文本",
            candidates=[{"position": 2, "current": "II"}],
        )
        assert a["text_snippet"] == "语境文本"
        assert len(a["candidates"]) == 1


class TestGenerateDuplicateCandidates:
    def test_single_duplicate(self):
        cands = generate_duplicate_candidates(
            ["I", "II", "II", "IV", "V"], [1, 2, 2, 4, 5]
        )
        assert len(cands) == 2  # replace + keep
        assert any(c["action"] == "replace_token" and c["token"] == "III" for c in cands)
        assert any(c["action"] == "keep_as_is" for c in cands)
        replace = next(c for c in cands if c["action"] == "replace_token")
        assert replace["position"] == 2
        assert replace["current_token"] == "II"

    def test_multiple_duplicates(self):
        cands = generate_duplicate_candidates(
            ["I", "I", "II", "II"], [1, 1, 2, 2]
        )
        assert len(cands) == 4  # 2 duplicates × 2 choices each

    def test_no_duplicate(self):
        cands = generate_duplicate_candidates(
            ["I", "II", "III"], [1, 2, 3]
        )
        assert cands == []


class TestGenerateGapCandidates:
    def test_single_gap(self):
        cands = generate_gap_candidates(
            ["I", "II", "IV", "V"], [1, 2, 4, 5]
        )
        assert len(cands) == 3  # insert + renumber + keep
        assert any(c["action"] == "insert_token" and c["token"] == "III" for c in cands)
        assert any(c["action"] == "replace_token_at_position" and c["token"] == "III" for c in cands)
        assert any(c["action"] == "keep_as_is" for c in cands)

    def test_multiple_gaps(self):
        cands = generate_gap_candidates(
            ["I", "IV", "V"], [1, 4, 5]
        )
        assert len(cands) == 3  # insert + renumber + keep (gap at position 1)

    def test_no_gap(self):
        cands = generate_gap_candidates(
            ["I", "II", "III"], [1, 2, 3]
        )
        assert cands == []


class TestGenerateDigitConfusionCandidates:
    def test_basic(self):
        cands = generate_digit_confusion_candidates("A", "1、II")
        assert len(cands) == 2  # replace + keep (flat)
        assert cands[0]["option_key"] == "A"
        assert cands[0]["option_text"] == "1、II"
        assert any(c["action"] == "replace_1_with_I" for c in cands)
        assert any(c["action"] == "keep_as_is" for c in cands)


class TestApplyRomanFix:
    def test_replace_token_in_stem(self):
        q = {"stem": "I. 第一\nII. 第二"}
        decision = {
            "action": "replace_token",
            "source": "stem",
            "position": 1,
            "from_token": "II",
            "to_token": "III",
        }
        result = apply_roman_fix(q, decision)
        assert "III. 第二" in result["stem"]

    def test_replace_1_with_I_in_option(self):
        q = {
            "stem": "I. 第一\nII. 第二",
            "options": [{"key": "A", "text": "1、I"}, {"key": "B", "text": "I、II"}],
        }
        decision = {
            "action": "replace_1_with_I",
            "source": "option_A",
            "original_fragment": "1、",
            "fixed_fragment": "I、",
        }
        result = apply_roman_fix(q, decision)
        opt_a = next(o for o in result["options"] if o["key"] == "A")
        assert opt_a["text"] == "I、I"

    def test_keep_as_is(self):
        q = {"stem": "原始文本"}
        decision = {"action": "keep_as_is"}
        result = apply_roman_fix(q, decision)
        assert result["stem"] == "原始文本"

    def test_unknown_action(self):
        q = {"stem": "原始文本"}
        result = apply_roman_fix(q, {"action": "nonexistent"})
        assert result["stem"] == "原始文本"

    def test_non_destructive(self):
        q = {"stem": "原始文本", "options": [{"key": "A", "text": "内容"}]}
        decision = {"action": "keep_as_is"}
        result = apply_roman_fix(q, decision)
        assert "options" in result
        assert result["options"][0]["text"] == "内容"


class TestDisambiguationWithOCRExample:
    """End-to-end test using the real OCR issue from docs/BUGS.md."""

    def test_duplicate_detection_on_bugs_example(self):
        tokens = ["I", "II", "II", "IV", "V"]
        values = [1, 2, 2, 4, 5]
        issue_type = classify_roman_issue(tokens, values)
        assert issue_type == DUPLICATE

        cands = generate_duplicate_candidates(tokens, values)
        assert len(cands) == 2  # replace + keep (flat)
        replace = next(c for c in cands if c["action"] == "replace_token")
        assert replace["token"] == "III"

    def test_gap_detection(self):
        tokens = ["I", "II", "IV", "V"]
        values = [1, 2, 4, 5]
        issue_type = classify_roman_issue(tokens, values)
        assert issue_type == GAP

    def test_clean_sequence_passes(self):
        assert classify_roman_issue(["I", "II", "III", "IV", "V"], [1, 2, 3, 4, 5]) == ""
