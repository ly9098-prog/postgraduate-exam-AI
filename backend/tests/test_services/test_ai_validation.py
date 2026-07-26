"""Tests for AI standardization result validation."""


from app.features.ai_validation import (
    _detect_duplicate_stem,
    _detect_field_pollution,
    _detect_length_anomaly,
    _detect_structure_anomalies,
    validate_ai_result,
    validate_ai_results,
)


class TestDetectDuplicateStem:
    def test_no_duplication(self):
        stem = "下列关于数据结构的说法正确的是"
        assert _detect_duplicate_stem(stem) is None

    def test_full_duplication(self):
        original = "下列关于数据结构的说法正确的是哪一个选项"
        stem = original + original
        result = _detect_duplicate_stem(stem)
        assert result is not None

    def test_repeated_fragment(self):
        stem = "下列关于数据结构的说法正确的是下列关于数据结构的说法正确的是选项A"
        result = _detect_duplicate_stem(stem)
        assert result is not None

    def test_short_stem_ignored(self):
        assert _detect_duplicate_stem("短题") is None

    def test_empty_stem(self):
        assert _detect_duplicate_stem("") is None


class TestDetectFieldPollution:
    def test_clean_fields(self):
        issues = _detect_field_pollution(
            stem="下列关于数据结构的说法正确的是",
            answer="A",
            analysis="因为数据结构包含元素和关系",
        )
        assert issues == []

    def test_answer_label_in_stem(self):
        issues = _detect_field_pollution(
            stem="下列关于数据结构的说法 答案：A 正确的是",
            answer="A",
            analysis="",
        )
        assert "answer_label_in_stem" in issues

    def test_answer_bracket_label_in_stem(self):
        issues = _detect_field_pollution(
            stem="题目内容 【答案】B 后续文字",
            answer="B",
            analysis="",
        )
        assert "answer_label_in_stem" in issues

    def test_analysis_label_in_stem(self):
        issues = _detect_field_pollution(
            stem="题目内容 解析：这是因为",
            answer="A",
            analysis="",
        )
        assert "analysis_label_in_stem" in issues

    def test_stem_content_leaked_into_answer(self):
        stem = "下列关于操作系统进程管理的说法正确的是"
        issues = _detect_field_pollution(
            stem=stem,
            answer="下列关于操作系统进程管理的说法正确的是A选项因为进程是资源分配的基本单位",
            analysis="",
        )
        assert "stem_content_in_answer" in issues


class TestDetectStructureAnomalies:
    def test_valid_question(self):
        q = {
            "stem": "题目",
            "options": [{"key": "A", "text": "选项A"}],
            "answer": "A",
            "confidence_score": 0.9,
        }
        assert _detect_structure_anomalies(q) == []

    def test_stem_not_string(self):
        q = {"stem": 123, "options": None, "answer": "A"}
        issues = _detect_structure_anomalies(q)
        assert "stem_not_string" in issues

    def test_answer_not_string(self):
        q = {"stem": "题目", "answer": ["A", "B"]}
        issues = _detect_structure_anomalies(q)
        assert "answer_not_string" in issues

    def test_options_invalid_type(self):
        q = {"stem": "题目", "options": "A,B,C,D"}
        issues = _detect_structure_anomalies(q)
        assert "options_invalid_type" in issues

    def test_option_item_not_dict(self):
        q = {"stem": "题目", "options": ["A", "B"]}
        issues = _detect_structure_anomalies(q)
        assert "option_item_not_dict" in issues

    def test_option_missing_key(self):
        q = {"stem": "题目", "options": [{"text": "选项A"}]}
        issues = _detect_structure_anomalies(q)
        assert "option_missing_key_or_text" in issues

    def test_confidence_out_of_range(self):
        q = {"stem": "题目", "confidence_score": 1.5}
        issues = _detect_structure_anomalies(q)
        assert "confidence_out_of_range" in issues

    def test_confidence_not_numeric(self):
        q = {"stem": "题目", "confidence_score": "high"}
        issues = _detect_structure_anomalies(q)
        assert "confidence_not_numeric" in issues

    def test_options_as_dict_valid(self):
        q = {"stem": "题目", "options": {"A": "选项A", "B": "选项B"}}
        issues = _detect_structure_anomalies(q)
        assert "options_invalid_type" not in issues


class TestDetectLengthAnomaly:
    def test_normal_length(self):
        assert _detect_length_anomaly("修复后题目", "原始文本内容") is None

    def test_too_long(self):
        result = _detect_length_anomaly("x" * 100, "short")
        assert result == "stem_too_long"

    def test_too_short(self):
        result = _detect_length_anomaly("x", "这是一段很长的原始文本内容用来测试")
        assert result == "stem_too_short"

    def test_empty_raw_text(self):
        assert _detect_length_anomaly("stem", "") is None

    def test_empty_stem(self):
        assert _detect_length_anomaly("", "raw") is None


class TestValidateAiResult:
    def test_valid_question(self):
        q = {
            "stem": "下列关于数据结构的说法正确的是",
            "options": [{"key": "A", "text": "选项"}],
            "answer": "A",
            "analysis": "解析内容",
            "raw_text": "1. 下列关于数据结构的说法正确的是",
            "confidence_score": 0.9,
        }
        result = validate_ai_result(q)
        assert result["is_valid"] is True
        assert result["severity"] == "none"
        assert result["issues"] == []

    def test_duplicated_stem_is_error(self):
        original = "下列关于操作系统的进程调度算法说法正确的是"
        q = {
            "stem": original + original,
            "answer": "A",
            "raw_text": original,
        }
        result = validate_ai_result(q)
        assert result["is_valid"] is False
        assert result["severity"] == "error"

    def test_field_pollution_is_warning(self):
        q = {
            "stem": "题目内容 解析：因为这样",
            "answer": "A",
            "analysis": "",
            "raw_text": "1. 题目内容",
        }
        result = validate_ai_result(q)
        assert "analysis_label_in_stem" in result["issues"]
        assert result["severity"] == "warning"


class TestValidateAiResults:
    def test_batch_validation(self):
        questions = [
            {"stem": "正常题目一", "answer": "A", "raw_text": "1. 正常题目一", "confidence_score": 0.9},
            {"stem": "正常题目二", "answer": "B", "raw_text": "2. 正常题目二", "confidence_score": 0.8},
        ]
        result = validate_ai_results(questions)
        assert result["stats"]["total"] == 2
        assert result["stats"]["valid"] == 2
        assert result["stats"]["errors"] == 0

    def test_mixed_results(self):
        original = "这是一道关于操作系统进程调度的考研真题选择题"
        questions = [
            {"stem": "正常题目", "answer": "A", "raw_text": "正常", "confidence_score": 0.9},
            {"stem": original + original, "answer": "A", "raw_text": original},
        ]
        result = validate_ai_results(questions)
        assert result["stats"]["valid"] == 1
        assert result["stats"]["errors"] == 1
        assert "ai_validation" in result["questions"][0]
        assert "ai_validation" in result["questions"][1]
