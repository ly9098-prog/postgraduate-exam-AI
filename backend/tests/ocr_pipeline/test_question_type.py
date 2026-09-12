"""题型领域模块综合测试。

覆盖：
- QuestionType 枚举完整性
- CANONICAL_TYPES 不可变性
- validate_question_type 严格校验
- normalize_question_type 别名规范化
- 工具函数 (is_canonical, is_choice_type, etc.)
- 元数据接口
- 安全别名可在导入边界转换
- 普通 Schema 拒绝 choice/fill/judge
- 未知值不回退为 single_choice
- NULL 仅在允许的模式中通过
"""

import pytest

from app.features.question_type import (
    CANONICAL_TYPES,
    QT_FILL_BLANK,
    QT_MULTI_BLANK_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_SUBJECTIVE,
    QT_TRUE_FALSE,
    QUESTION_TYPE_CAPABILITIES,
    QUESTION_TYPE_LABELS,
    QUESTION_TYPE_SORT_ORDER,
    QuestionType,
    get_question_type_metadata_items,
    is_canonical,
    is_choice_type,
    is_multi_blank_type,
    is_multiple_choice_type,
    is_true_false_type,
    normalize_question_type,
    validate_question_type,
)


class TestQuestionTypeEnum:
    """QuestionType 枚举完整性。"""

    def test_has_exactly_6_members(self):
        assert len(QuestionType) == 6

    def test_values_are_unique(self):
        values = [m.value for m in QuestionType]
        assert len(values) == len(set(values))

    def test_canonical_types_matches_enum(self):
        assert frozenset(m.value for m in QuestionType) == CANONICAL_TYPES

    def test_labels_cover_all_types(self):
        assert set(QUESTION_TYPE_LABELS.keys()) == set(QuestionType)

    def test_capabilities_cover_all_types(self):
        assert set(QUESTION_TYPE_CAPABILITIES.keys()) == set(QuestionType)

    def test_sort_order_cover_all_types(self):
        assert set(QUESTION_TYPE_SORT_ORDER.keys()) == set(QuestionType)

    def test_canonical_types_is_frozenset(self):
        assert isinstance(CANONICAL_TYPES, frozenset)
        assert QT_SINGLE_CHOICE in CANONICAL_TYPES

    def test_unknown_not_in_enum(self):
        for m in QuestionType:
            assert m.value != "unknown"

    def test_choice_not_in_enum(self):
        for m in QuestionType:
            assert m.value != "choice"

    def test_fill_not_in_enum(self):
        for m in QuestionType:
            assert m.value != "fill"

    def test_judgement_not_in_enum(self):
        for m in QuestionType:
            assert m.value != "judgement"

    def test_metadata_items_sorted(self):
        items = get_question_type_metadata_items()
        assert len(items) == 6
        orders = [item["sort_order"] for item in items]
        assert orders == sorted(orders)


class TestValidateQuestionType:
    """validate_question_type 严格校验。"""

    def test_accepts_canonical_codes(self):
        assert validate_question_type(QT_SINGLE_CHOICE) == QT_SINGLE_CHOICE
        assert validate_question_type(QT_MULTIPLE_CHOICE) == QT_MULTIPLE_CHOICE
        assert validate_question_type(QT_TRUE_FALSE) == QT_TRUE_FALSE
        assert validate_question_type(QT_FILL_BLANK) == QT_FILL_BLANK
        assert validate_question_type(QT_MULTI_BLANK_CHOICE) == QT_MULTI_BLANK_CHOICE
        assert validate_question_type(QT_SUBJECTIVE) == QT_SUBJECTIVE

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="不能为空"):
            validate_question_type(None)

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="不能为空"):
            validate_question_type("")

    def test_rejects_choice(self):
        with pytest.raises(ValueError, match="非标准"):
            validate_question_type("choice")

    def test_rejects_fill(self):
        with pytest.raises(ValueError, match="非标准"):
            validate_question_type("fill")

    def test_rejects_judge(self):
        with pytest.raises(ValueError, match="非标准"):
            validate_question_type("judge")

    def test_rejects_judgement(self):
        with pytest.raises(ValueError, match="非标准"):
            validate_question_type("judgement")

    def test_rejects_unknown(self):
        with pytest.raises(ValueError, match="非标准"):
            validate_question_type("unknown")

    def test_rejects_nonsense(self):
        with pytest.raises(ValueError, match="非标准"):
            validate_question_type("not_a_real_type")

    def test_error_message_includes_standard_values(self):
        with pytest.raises(ValueError) as exc:
            validate_question_type("foo")
        assert "single_choice" in str(exc.value)
        assert "fill_blank" in str(exc.value)


class TestNormalizeQuestionType:
    """normalize_question_type 别名规范化（用于导入边界）。"""

    def test_canonical_passthrough(self):
        code, warns = normalize_question_type(QT_SINGLE_CHOICE)
        assert code == QT_SINGLE_CHOICE
        assert warns == []

    def test_choice_alias(self):
        code, warns = normalize_question_type("choice")
        assert code == QT_SINGLE_CHOICE
        assert any("choice" in w for w in warns)

    def test_fill_alias(self):
        code, warns = normalize_question_type("fill")
        assert code == QT_FILL_BLANK

    def test_judge_alias(self):
        code, warns = normalize_question_type("judge")
        assert code == QT_TRUE_FALSE

    def test_judgement_alias(self):
        code, warns = normalize_question_type("judgement")
        assert code == QT_TRUE_FALSE

    def test_multi_choice_alias(self):
        code, warns = normalize_question_type("multi_choice")
        assert code == QT_MULTIPLE_CHOICE

    @pytest.mark.parametrize("alias", [
        "choice", "single", "singlechoice", "single-choice",
    ])
    def test_single_choice_aliases(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_SINGLE_CHOICE, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "multiple", "multiplechoice", "multi_choice",
    ])
    def test_multiple_choice_aliases(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_MULTIPLE_CHOICE, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "fill", "blank", "fillblank",
    ])
    def test_fill_blank_aliases(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_FILL_BLANK, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "judge", "judgement", "judgment",
    ])
    def test_true_false_aliases(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_TRUE_FALSE, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "单选", "单选题", "单项选择",
    ])
    def test_chinese_single_choice(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_SINGLE_CHOICE, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "多选", "多选题", "多项选择",
    ])
    def test_chinese_multiple_choice(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_MULTIPLE_CHOICE, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "判断", "判断题", "对错", "是非题",
    ])
    def test_chinese_true_false(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_TRUE_FALSE, f"{alias} → {code}"

    @pytest.mark.parametrize("alias", [
        "填空", "填空题",
    ])
    def test_chinese_fill_blank(self, alias):
        code, warns = normalize_question_type(alias)
        assert code == QT_FILL_BLANK, f"{alias} → {code}"

    def test_case_insensitive(self):
        code, warns = normalize_question_type("Single_Choice")
        assert code == QT_SINGLE_CHOICE

    def test_whitespace_trim(self):
        code, warns = normalize_question_type("  single_choice  ")
        assert code == QT_SINGLE_CHOICE

    def test_hyphen_to_underscore(self):
        code, warns = normalize_question_type("single-choice")
        assert code == QT_SINGLE_CHOICE

    def test_unknown_value_returns_none(self):
        code, warns = normalize_question_type("gibberish_123")
        assert code is None
        assert len(warns) > 0

    def test_none_returns_none(self):
        code, warns = normalize_question_type(None)
        assert code is None

    def test_empty_string_returns_none(self):
        code, warns = normalize_question_type("")
        assert code is None

    def test_does_not_guess_unknown(self):
        """未知值不回退为 single_choice。"""
        code, warns = normalize_question_type("custom_type_42")
        assert code is None

    def test_canonical_code_is_self_alias(self):
        code, warns = normalize_question_type(QT_MULTI_BLANK_CHOICE)
        assert code == QT_MULTI_BLANK_CHOICE
        assert warns == []


class TestHelperFunctions:
    """工具函数测试。"""

    @pytest.mark.parametrize("code", [
        QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE, QT_TRUE_FALSE,
        QT_FILL_BLANK, QT_MULTI_BLANK_CHOICE, QT_SUBJECTIVE,
    ])
    def test_is_canonical_accepts_all_standard(self, code):
        assert is_canonical(code)

    def test_is_canonical_rejects_none(self):
        assert not is_canonical(None)

    def test_is_canonical_rejects_choice(self):
        assert not is_canonical("choice")

    def test_choice_type(self):
        assert is_choice_type(QT_SINGLE_CHOICE)
        assert not is_choice_type(QT_MULTIPLE_CHOICE)
        assert not is_choice_type(None)

    def test_multi_blank_type(self):
        assert is_multi_blank_type(QT_MULTI_BLANK_CHOICE)
        assert not is_multi_blank_type(QT_FILL_BLANK)

    def test_multiple_choice_type(self):
        assert is_multiple_choice_type(QT_MULTIPLE_CHOICE)
        assert not is_multiple_choice_type(QT_SINGLE_CHOICE)

    def test_true_false_type_accepts_canonical(self):
        assert is_true_false_type(QT_TRUE_FALSE)
        assert not is_true_false_type(QT_SINGLE_CHOICE)

    def test_true_false_type_rejects_judgement(self):
        """is_true_false_type 只认标准 code，不直接接受 judgement。"""
        assert not is_true_false_type("judgement")
