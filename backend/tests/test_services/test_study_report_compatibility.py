"""学习报告纯函数兼容基线。

覆盖 study_report_service 中可脱离数据库独立测试的纯规则：
- _safe_accuracy：安全正确率计算
- _extract_title：题目内容标题提取
- _classify_mastery：掌握度分类
- _mastery_suggestion：掌握度建议文案
- _calc_priority：优先级计算
"""

from __future__ import annotations

from app.services.study_report_service import (
    _calc_priority,
    _classify_mastery,
    _extract_title,
    _mastery_suggestion,
    _safe_accuracy,
)


class TestSafeAccuracy:
    """_safe_accuracy 计算百分比正确率，除零返回 0。"""

    def test_zero_total_returns_zero(self) -> None:
        assert _safe_accuracy(5, 0) == 0.0

    def test_full_accuracy(self) -> None:
        assert _safe_accuracy(10, 10) == 100.0

    def test_half_accuracy(self) -> None:
        assert _safe_accuracy(5, 10) == 50.0

    def test_rounds_two_decimals(self) -> None:
        assert _safe_accuracy(1, 3) == 33.33

    def test_zero_correct(self) -> None:
        assert _safe_accuracy(0, 10) == 0.0


class TestExtractTitle:
    """_extract_title 从题目内容 JSON 提取前 100 字符。"""

    def test_none_returns_empty(self) -> None:
        assert _extract_title(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_title("") == ""

    def test_plain_string_truncated(self) -> None:
        long = "A" * 150
        result = _extract_title(long)
        assert len(result) == 100
        assert result == "A" * 100

    def test_plain_string_short(self) -> None:
        assert _extract_title("短文本") == "短文本"

    def test_json_string_with_text_segment(self) -> None:
        content = '[{"type": "text", "text": "题干内容"}]'
        assert _extract_title(content) == "题干内容"

    def test_list_with_text_segment(self) -> None:
        content = [{"type": "text", "text": "题干"}]
        assert _extract_title(content) == "题干"

    def test_list_without_text_segment(self) -> None:
        content = [{"type": "image", "url": "http://x"}]
        assert _extract_title(content) == ""

    def test_invalid_json_string(self) -> None:
        assert _extract_title("{invalid json") == ""

    def test_long_text_segment_truncated(self) -> None:
        text = "B" * 150
        content = [{"type": "text", "text": text}]
        result = _extract_title(content)
        assert len(result) == 100


class TestClassifyMastery:
    """_classify_mastery 根据置信度和掌握度分数分类。"""

    def test_low_confidence_unknown(self) -> None:
        assert _classify_mastery(0.2, 90) == "unknown"

    def test_weak(self) -> None:
        assert _classify_mastery(0.5, 30) == "weak"

    def test_normal(self) -> None:
        assert _classify_mastery(0.5, 50) == "normal"

    def test_good(self) -> None:
        assert _classify_mastery(0.5, 75) == "good"

    def test_mastered(self) -> None:
        assert _classify_mastery(0.5, 90) == "mastered"

    def test_boundary_confidence(self) -> None:
        assert _classify_mastery(0.3, 90) == "mastered"

    def test_boundary_weak(self) -> None:
        assert _classify_mastery(0.5, 40) == "normal"

    def test_boundary_normal(self) -> None:
        assert _classify_mastery(0.5, 70) == "good"

    def test_boundary_good(self) -> None:
        assert _classify_mastery(0.5, 85) == "mastered"


class TestMasterySuggestion:
    """_mastery_suggestion 返回掌握度建议文案。"""

    def test_weak(self) -> None:
        assert "优先" in _mastery_suggestion("weak")

    def test_normal(self) -> None:
        assert "保持" in _mastery_suggestion("normal")

    def test_good(self) -> None:
        assert "低频" in _mastery_suggestion("good")

    def test_mastered(self) -> None:
        assert "稳定" in _mastery_suggestion("mastered")

    def test_unknown(self) -> None:
        assert "数据" in _mastery_suggestion("unknown")

    def test_invalid_status_returns_empty(self) -> None:
        assert _mastery_suggestion("invalid") == ""


class TestCalcPriority:
    """_calc_priority 根据逾期天数、错题数和盒子等级计算优先级。"""

    def test_high_overdue(self) -> None:
        assert _calc_priority(3, 0, 5) == "high"

    def test_high_wrong_count(self) -> None:
        assert _calc_priority(0, 3, 5) == "high"

    def test_high_low_box(self) -> None:
        assert _calc_priority(0, 0, 1) == "high"

    def test_medium_overdue(self) -> None:
        assert _calc_priority(1, 0, 5) == "medium"

    def test_medium_wrong_count(self) -> None:
        assert _calc_priority(0, 1, 5) == "medium"

    def test_normal(self) -> None:
        assert _calc_priority(0, 0, 5) == "normal"
